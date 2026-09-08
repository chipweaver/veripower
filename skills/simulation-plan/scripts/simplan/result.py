import datetime
import json
import sys
from pathlib import Path

from simplan._plan import SIDECAR_NAMES

STAGE = "simulation-plan"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(*, status, stage_specific, artifacts, fix_owner=None) -> dict:
    """fix_owner rides on a failure only, and only when the caller named one: its ABSENCE is
    what decide reads as "this stage cannot tell", so it must never serialize empty."""
    if status == "fail" and fix_owner:
        stage_specific = {**stage_specific, "fix_owner": fix_owner}
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
    sys.stdout.write(
        f"[simplan finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def enumerate_artifacts(workdir) -> list:
    """Fixed simulation-plan artifact set, present-only. Never lists result.json (self) —
    the envelope schema forbids it. The review leaves as one tree, whatever the reviewer
    called the files in it, so the endorsement reads back the set that was delivered.
    Present-only keeps a seeded rework workdir carrying the full prior product set, so a
    promoted fail cannot GC canonical down to a hollow view."""
    workdir = Path(workdir)
    fixed = [
        "verification-plan.md",
        *SIDECAR_NAMES,
    ]
    reviews = ["plan-review"] if (workdir / "plan-review").is_dir() else []
    return [{"path": p} for p in fixed + reviews if (workdir / p).exists()]


def build_result(
    workdir, spec_workdir, *, revision, fail_reason=None, fix_owner=None
) -> int:
    """Assemble the lean simulation-plan result.json from the workdir.

    The pass path re-runs check-scaffold in-process. It was clean at the script gate and every layer
    of it is a set operation over the plan sidecars plus the authored check hints, so a
    failure now means an artifact was edited after the gate — BLOCKED rather than a routable
    fail. The fail path does not run it: an early-fail workdir may hold no sidecars at all,
    and a fail-loud exit there would turn a routable fail into a BLOCKED.

    The plan-adequacy review is NOT re-judged here, and re-adding that would not buy a check:
    a verdict re-derived from the record would be checked against the record's own author.

    The status is derived: a round either delivered the plan or the caller says in one line what
    stopped it. There is no human verdict to carry — the review is prose nothing reduces to a
    pass, and the act that endorses it is `kernel.py pin`, which anchors to its content and is
    what signoff requires. `revision` is an amendment marker, not an outcome.
    Returns 0 (result.json written, pass or fail). A raise -> finalize() exit 2 (BLOCKED)."""
    workdir = Path(workdir)

    if fail_reason:
        ss = {"fail_reason": fail_reason}
        if revision:
            ss["revision"] = revision
        _write_result(
            workdir,
            _envelope(
                status="fail",
                stage_specific=ss,
                artifacts=enumerate_artifacts(workdir),
                fix_owner=fix_owner,
            ),
        )
        return 0

    from simplan.scaffold import verdict

    errors = verdict(workdir, spec_workdir)
    if errors:
        listed = "; ".join(errors)
        raise ValueError(
            f"check-scaffold no longer passes at finalize — {listed}. The script gate left it "
            "clean, "
            "so an artifact was edited after the gate: repair it, do not finalize."
        )

    ss = {}
    if revision:
        ss["revision"] = revision
    _write_result(
        workdir,
        _envelope(
            status="pass",
            stage_specific=ss,
            artifacts=enumerate_artifacts(workdir),
            fix_owner=fix_owner,
        ),
    )
    return 0


def finalize(
    workdir, spec_workdir, *, revision, fail_reason=None, fix_owner=None
) -> int:
    """build_result, with the exit-code contract. exit 0 = result.json written (pass or fail);
    exit 2 = BLOCKED (an empty --fail-reason, a re-run check-scaffold failure, or any internal
    raise) — never conflated with status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[simplan finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(
            workdir,
            spec_workdir,
            revision=revision,
            fail_reason=fail_reason,
            fix_owner=fix_owner,
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[simplan finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
