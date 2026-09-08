import datetime
import json
import sys
from pathlib import Path

from spec import ledger
from spec.constraints import derive_constraints
from spec.crossrefs import verdict as crossrefs_verdict

STAGE = "specification"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(*, status, stage_specific, artifacts) -> dict:
    return {
        "stage": STAGE,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": artifacts,
        "stage_specific": stage_specific,
    }


def _write_result(workdir: Path, env: dict) -> None:
    tmp = workdir / "result.json.tmp"
    tmp.write_text(json.dumps(env, indent=2) + "\n")
    tmp.replace(workdir / "result.json")  # atomic: never observed half-written
    print(f"[spec finalize] wrote {workdir / 'result.json'} (status={env['status']})")


def _top_from_manifest(workdir: Path) -> str:
    """<TOP> = manifest.module — the same source derive_constraints reads; needed on the fail
    path, which never runs the derivation. Indexed, not defaulted: <TOP> names the two
    constraint files in artifacts[], so a roster this could not resolve would promote a fail
    with those entries silently filtered out. Raising makes it BLOCKED. The one site that
    reports an absent manifest.module as a defect is check_purity, at the ledger and partition gate."""
    manifest = json.loads((Path(workdir) / "manifest.json").read_text(encoding="utf-8"))
    return manifest["module"]


def enumerate_artifacts(workdir: Path, top: str) -> list[dict]:
    """Fixed specification artifact set, present-only. NEVER lists brainstorm.md
    (module-root, outside the workdir — would break promote()) or result.json (self).

    The child designs and the reviews each leave as one tree, so however the decomposition lays
    them out inside those directories they are delivered and versioned together — each is read
    downstream, or endorsed, as a set, so this needs no roster: <TOP>
    is the caller's (build_result reads manifest.module, and an unreadable manifest is BLOCKED
    there)."""
    workdir = Path(workdir)
    fixed = [
        "design.md",
        "manifest.json",
        f"constraints/{top}.sdc",
        f"constraints/{top}.sgdc",
        "requirements.json",
        "clocks.json",
        "top-io.json",
        "interconnects.json",
        "check-hints.json",
    ]
    child_docs = ["children"] if (workdir / "children").is_dir() else []
    reviews = ["spec-review"] if (workdir / "spec-review").is_dir() else []
    return [{"path": p} for p in fixed + child_docs + reviews if (workdir / p).exists()]


def build_result(workdir, fail_reason=None) -> int:
    """Assemble the lean specification result.json. Returns 0 (written, pass or fail); a
    raise becomes finalize exit 2 (BLOCKED).

    The status is derived, not supplied: a round either delivered what the stage owes or the
    caller says in one line what stopped it. There is no human verdict to carry — the reviews
    are prose nothing reduces to a pass, and the act that endorses them is `kernel.py pin`,
    which anchors to their content and is what signoff requires.

    Both re-derivations on the pass path were clean at the cross-reference gate, so a failure now
    artifact was edited after the gate — hence BLOCKED rather than a routable fail. The
    fail path runs neither: an early-fail's inputs may be incomplete, and derive_constraints'
    fail-loud exit would turn a routable fail into a BLOCKED.

    The semantic review is NOT re-judged here, and re-adding that would not buy a check: a
    verdict re-derived from the record would be checked against the --status of the same
    caller that assembled the record."""
    workdir = Path(workdir)

    if fail_reason:
        # An early exit outside the derivable set: a sub-Task could not deliver, or an input is
        # malformed, so no verdict can be re-derived. Record the caller's one-line reason.
        top = _top_from_manifest(workdir)
        _write_result(
            workdir,
            _envelope(
                status="fail",
                stage_specific={"fail_reason": fail_reason},
                artifacts=enumerate_artifacts(workdir, top),
            ),
        )
        return 0

    xrefs = crossrefs_verdict(workdir)
    if xrefs["status"] == "fail":
        listed = "; ".join(f"{v['where']}: {v['what']}" for v in xrefs["violations"])
        raise ValueError(
            f"check-crossrefs no longer passes at finalize — {listed}. The cross-reference gate left it clean, "
            "so an artifact was edited after the gate: repair it, do not finalize."
        )

    info = derive_constraints(
        workdir
    )  # reuse: resolves <TOP> + regenerates SDC/SGDC + self-checks
    top = info["top"]  # == manifest.module (the single <TOP> source)

    rows = ledger.load(
        workdir
    )  # re-validated in place; it is the SSoT every stage binds
    open_rows = ledger.unassignable(rows)
    if open_rows:
        raise ValueError(
            f"requirements.json still has unassignable rows {open_rows}: the ledger and partition gate resolves "
            "them before finalize."
        )

    artifacts = enumerate_artifacts(workdir, top)
    _write_result(
        workdir,
        _envelope(status="pass", stage_specific={}, artifacts=artifacts),
    )
    return 0


def finalize(workdir, *, fail_reason=None) -> int:
    """build_result, with the exit-code contract. exit 0 = result.json written (pass or fail);
    exit 2 = BLOCKED (an empty --fail-reason, an invalid or unresolved requirements.json, an
    unreadable manifest, a derivation fail-loud, or any internal raise) — never conflated with
    status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[spec finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(workdir, fail_reason=fail_reason)
    except SystemExit as exc:
        # derive_constraints' fail-loud sys.exit is a BaseException; keep the
        # documented exit-code contract (2 = BLOCKED) instead of leaking exit 1.
        print(f"[spec finalize] BLOCKED: {exc.code or exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[spec finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
