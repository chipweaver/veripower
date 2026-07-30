import datetime
import json
import sys
from pathlib import Path

from spec.constraints import derive_constraints
from spec.crossrefs import verdict as crossrefs_verdict
from spec.sidecar import SidecarError, read_sidecar, validate_doc

STAGE = "specification"

_REJECT_REASON = "design.md gate rejected at human review"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts) -> dict:
    return {
        "stage": STAGE,
        "module": module,
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


def _write_ppa_json(workdir: Path, ppa_targets: list) -> None:
    """The stable PPA-targets sidecar synthesis/power-analysis read directly — same
    atomic temp+rename as result.json. Written only on an explicit --ppa-targets
    override; otherwise the Wave-1-authored disk copy IS the source and stays untouched."""
    tmp = workdir / "ppa.json.tmp"
    tmp.write_text(json.dumps(ppa_targets, indent=2) + "\n")
    tmp.replace(workdir / "ppa.json")


def _top_from_manifest(workdir: Path) -> str:
    """<TOP> = manifest.module — the same source derive_constraints pins; read directly on
    the fail path, which never runs the derivation. With no manifest there is no artifact set
    to enumerate, so an unreadable one raises (finalize → exit 2 BLOCKED)."""
    manifest = json.loads((Path(workdir) / "manifest.json").read_text(encoding="utf-8"))
    top = manifest.get("module")
    if not top:
        raise ValueError("manifest.json missing 'module' (the <TOP> name)")
    return top


def enumerate_artifacts(workdir: Path, top: str) -> list[dict]:
    """Fixed specification artifact set, present-only. NEVER lists brainstorm.md
    (module-root, outside the workdir — would break promote()) or result.json (self)."""
    workdir = Path(workdir)
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    fixed = [
        "design.md",
        "manifest.json",
        "spec-review/decisions.md",
        f"constraints/{top}.sdc",
        f"constraints/{top}.sgdc",
        "ppa.json",
        "clocks.json",
        "features.json",
        "top-io.json",
        "interconnects.json",
    ]
    child_docs = [c["doc"] for c in manifest.get("children", []) if c.get("doc")]
    child_hints = [
        f"check-hints/{c['name']}.json"
        for c in manifest.get("children", [])
        if c.get("name")
    ]
    child_reviews = [
        f"spec-review/{c['name']}.md"
        for c in manifest.get("children", [])
        if c.get("name")
    ]
    return [
        {"path": p}
        for p in fixed + child_docs + child_hints + child_reviews
        if (workdir / p).is_file()
    ]


def build_result(workdir, module, ppa_targets, status, fail_reason=None) -> int:
    """Assemble the lean specification result.json. Returns 0 (written, pass or fail); a
    raise becomes finalize exit 2 (BLOCKED).

    Both re-derivations on the pass path were clean at Step 5, so a failure now means an
    artifact was edited after the gate — hence BLOCKED rather than a routable fail. The
    fail path runs neither: an early-fail's inputs may be incomplete, and derive_constraints'
    fail-loud exit would turn a routable fail into a BLOCKED.

    The semantic review is NOT re-judged here. It is prose under spec-review/, promoted and
    fingerprinted as this stage's proposed oracle; a script re-reducing it to a verdict would
    only be checking a record against the same agent's own --status, and pin/signoff is where
    that endorsement is actually held to account."""
    workdir = Path(workdir)

    if status == "fail":
        top = _top_from_manifest(workdir)
        ss = {"top_module": top, "fail_reason": fail_reason or _REJECT_REASON}
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=enumerate_artifacts(workdir, top),
            ),
        )
        return 0

    xrefs = crossrefs_verdict(workdir)
    if xrefs["status"] == "fail":
        listed = "; ".join(f"{v['where']}: {v['what']}" for v in xrefs["violations"])
        raise ValueError(
            f"check-crossrefs no longer passes at finalize — {listed}. Step 5 left it clean, "
            "so an artifact was edited after the gate: repair it, do not finalize."
        )

    info = derive_constraints(
        workdir
    )  # reuse: resolves <TOP> + regenerates SDC/SGDC + self-checks
    top = info["top"]  # == manifest.module (the single <TOP> source)

    if ppa_targets is not None:
        # Validate before writing: a malformed override must not clobber the sidecar.
        violations = validate_doc("ppa.json", ppa_targets)
        if violations:
            raise SidecarError("--ppa-targets override", violations)
        _write_ppa_json(workdir, ppa_targets)
    else:
        # The Wave-1 sidecar IS the PPA SSoT synthesis / power-analysis read directly, so it
        # is re-validated in place and never copied into this envelope.
        read_sidecar(workdir, "ppa.json")

    ss = {"top_module": top}
    artifacts = enumerate_artifacts(workdir, top)
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def finalize(
    workdir,
    module,
    *,
    status,
    ppa_targets_json=None,
    fail_reason=None,
) -> int:
    """Parse the human-gate outcome args, then build_result. --ppa-targets is an optional
    override — by default the Wave-1-authored {workdir}/ppa.json is read from disk. exit
    0 = result.json written (pass or fail); exit 2 = BLOCKED (bad --ppa-targets JSON, empty
    --fail-reason, missing/invalid ppa.json, unreadable manifest, a derivation fail-loud, or
    any internal raise) — never conflated with status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[spec finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    try:
        ppa = json.loads(ppa_targets_json) if ppa_targets_json is not None else None
    except json.JSONDecodeError as exc:
        print(
            f"[spec finalize] BLOCKED: --ppa-targets not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(workdir, module, ppa, status, fail_reason=fail_reason)
    except SystemExit as exc:
        # derive_constraints' fail-loud sys.exit is a BaseException; keep the
        # documented exit-code contract (2 = BLOCKED) instead of leaking exit 1.
        print(f"[spec finalize] BLOCKED: {exc.code or exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[spec finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
