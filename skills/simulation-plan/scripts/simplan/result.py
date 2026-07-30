import datetime
import json
import sys
from pathlib import Path

from simplan._plan import SIDECAR_NAMES

STAGE = "simulation-plan"

_REJECT_REASON = "user rejected plan"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts, fix_owner=None) -> dict:
    """fix_owner rides on a failure only, and only when the caller named one: its ABSENCE is
    what decide reads as "this stage cannot tell", so it must never serialize empty."""
    if status == "fail" and fix_owner:
        stage_specific = {**stage_specific, "fix_owner": fix_owner}
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
    sys.stdout.write(
        f"[simplan finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def enumerate_artifacts(workdir) -> list:
    """Fixed simulation-plan artifact set, present-only. Never lists result.json (self) —
    the envelope schema forbids it. Present-only keeps a seeded rework workdir carrying the
    full prior product set, so a promoted fail cannot GC canonical down to a hollow view."""
    workdir = Path(workdir)
    fixed = [
        "verification-plan.md",
        *SIDECAR_NAMES,
        "plan-review/review.md",
        "plan-review/decisions.md",
    ]
    return [{"path": p} for p in fixed if (workdir / p).is_file()]


def build_result(
    workdir, module, spec_workdir, *, status, revision, fail_reason=None, fix_owner=None
) -> int:
    """Assemble the lean simulation-plan result.json from the workdir.

    The pass path re-runs check-scaffold in-process. It was clean at Step 2 and every layer
    of it is a set operation over the plan sidecars plus the authored check hints, so a
    failure now means an artifact was edited after the gate — BLOCKED rather than a routable
    fail. The fail path does not run it: an early-fail workdir may hold no sidecars at all,
    and a fail-loud exit there would turn a routable fail into a BLOCKED.

    The plan-adequacy review is NOT re-judged here. It is prose under plan-review/, promoted
    and fingerprinted as this stage's proposed oracle; a script re-reducing it to a verdict
    would only be checking a record against the same agent's own --status, and pin/signoff is
    where that endorsement is actually held to account.

    The human-gate state (status=user-reject / revision) is passed in by the caller, NOT
    derivable from any artifact.
    Returns 0 (result.json written, pass or fail). A raise -> finalize() exit 2 (BLOCKED)."""
    workdir = Path(workdir)

    if status == "fail":
        if (
            fail_reason is None
            and not (workdir / "plan-review" / "review.md").is_file()
        ):
            # A user reject can only follow the Step-3 review and the Step-4 loop, and the
            # reviewer — not this caller — writes that file. A bare --status fail on a
            # workdir where no review ran would fabricate a human rejection; force the
            # caller to say what failed instead.
            raise ValueError(
                "--status fail without --fail-reason is the user reject and requires "
                "plan-review/review.md on disk; for an early fail pass --fail-reason"
            )
        ss = {"fail_reason": fail_reason or _REJECT_REASON}
        if revision:
            ss["revision"] = revision
        _write_result(
            workdir,
            _envelope(
                module,
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
            f"check-scaffold no longer passes at finalize — {listed}. Step 2 left it clean, "
            "so an artifact was edited after the gate: repair it, do not finalize."
        )

    ss = {}
    if revision:
        ss["revision"] = revision
    _write_result(
        workdir,
        _envelope(
            module,
            status="pass",
            stage_specific=ss,
            artifacts=enumerate_artifacts(workdir),
            fix_owner=fix_owner,
        ),
    )
    return 0


def finalize(
    workdir, module, spec_workdir, *, status, revision, fail_reason=None, fix_owner=None
) -> int:
    """Parse the human-gate outcome args, then build_result. exit 0 = result.json written
    (pass or fail); exit 2 = BLOCKED (empty --fail-reason, a re-run check-scaffold failure,
    or any internal raise) — never conflated with status=fail."""
    if fail_reason is not None and not fail_reason.strip():
        print(
            "[simplan finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2
    if fail_reason is not None and status != "fail":
        # An unpaired --fail-reason is a caller slip about to invert a failure into a
        # computed pass; refuse loudly instead of silently discarding the reason.
        print(
            "[simplan finalize] BLOCKED: --fail-reason requires --status fail",
            file=sys.stderr,
        )
        return 2
    try:
        return build_result(
            workdir,
            module,
            spec_workdir,
            status=status,
            revision=revision,
            fail_reason=fail_reason,
            fix_owner=fix_owner,
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[simplan finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
