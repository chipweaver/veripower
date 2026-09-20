import datetime
import json
import sys
from pathlib import Path

STAGE = "simulation-plan"


def enumerate_artifacts(workdir) -> list:
    """Fixed simulation-plan artifact set, present-only. Never lists result.json (self) —
    the envelope schema forbids it. The review leaves as one tree, whatever the reviewer
    called the files in it, so its recorded fingerprint covers the delivered set.
    Present-only keeps a seeded rework workdir carrying the full prior product set, so a
    promoted fail cannot GC canonical down to a hollow view."""
    workdir = Path(workdir)
    fixed = [
        "verification-plan.md",
        "tb-scaffold.json",
        "sequences.json",
        "power-scenarios.json",
    ]
    reviews = ["plan-review"] if (workdir / "plan-review").is_dir() else []
    return [{"path": p} for p in fixed + reviews if (workdir / p).exists()]


def finalize(workdir, spec_workdir, *, fail_reason=None, fix_owner=None) -> int:
    """Assess the stage and write its result. Input or I/O errors leave no current result."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if fail_reason is not None and (not fail_reason.strip()):
        print(
            "[simplan finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2

    def _write_result(*, status, stage_specific, artifacts):
        if status == "fail" and fix_owner:
            stage_specific = {**stage_specific, "fix_owner": fix_owner}
        result = {
            "stage": STAGE,
            "produced_at": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "status": status,
            "artifacts": artifacts,
            "stage_specific": stage_specific,
        }
        result_path = Path(workdir) / "result.json"
        temporary_path = result_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(result, indent=2) + "\n")
        temporary_path.replace(result_path)
        print(f"[simplan finalize] Written: {result_path} (status={status})")
        return 0

    try:
        workdir = Path(workdir)
        if fail_reason:
            stage_specific = {"fail_reason": fail_reason}
            return _write_result(
                status="fail",
                stage_specific=stage_specific,
                artifacts=enumerate_artifacts(workdir),
            )
        from simplan.scaffold import verdict

        errors = verdict(workdir, spec_workdir)
        if errors:
            listed = "; ".join(errors)
            raise ValueError(
                f"check-scaffold failed: {listed}. Repair the plan or report the unresolved cause."
            )
        return _write_result(
            status="pass", stage_specific={}, artifacts=enumerate_artifacts(workdir)
        )
    except (OSError, ValueError) as exc:
        print(f"[simplan finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
