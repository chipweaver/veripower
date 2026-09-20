import datetime
import json
import sys
from pathlib import Path

from spec.constraints import derive_constraints
from spec.crossrefs import verdict as crossrefs_verdict
from spec.sidecar import SidecarError, read_sidecar

STAGE = "specification"


def enumerate_artifacts(workdir: Path, top: str) -> list[dict]:
    """Fixed specification artifact set, present-only. NEVER lists brainstorm.md
    (module-root, outside the workdir — would break promote()) or result.json (self).

    The reviews leave as one tree, so however they are laid out inside it they are delivered and
    versioned together, which needs no roster: <TOP>
    is the caller's (finalize reads manifest.module, and an unreadable manifest is BLOCKED
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
        "check-hints.json",
    ]
    reviews = ["spec-review"] if (workdir / "spec-review").is_dir() else []
    return [{"path": p} for p in fixed + reviews if (workdir / p).exists()]


def finalize(workdir, *, fail_reason=None) -> int:
    """Assess the stage and write its result. Input or I/O errors leave no current result."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if fail_reason is not None and (not fail_reason.strip()):
        print(
            "[spec finalize] BLOCKED: --fail-reason must be a non-empty one-line reason",
            file=sys.stderr,
        )
        return 2

    def _write_result(*, status, stage_specific, artifacts):
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
        print(f"[spec finalize] Written: {result_path} (status={status})")
        return 0

    try:
        workdir = Path(workdir)
        if fail_reason:
            top = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))[
                "module"
            ]
            return _write_result(
                status="fail",
                stage_specific={"fail_reason": fail_reason},
                artifacts=enumerate_artifacts(workdir, top),
            )
        xrefs = crossrefs_verdict(workdir)
        if xrefs["status"] == "fail":
            listed = "; ".join(
                (f"{v['where']}: {v['what']}" for v in xrefs["violations"])
            )
            raise ValueError(
                f"check-crossrefs failed: {listed}. Repair the inconsistent input or report the unresolved cause."
            )
        info = derive_constraints(workdir)
        top = info["top"]
        rows = read_sidecar(workdir, "requirements.json")
        open_rows = [row["id"] for row in rows if row["judge"] == "unassignable"]
        if open_rows:
            raise ValueError(
                f"requirements.json still has unassignable rows {open_rows}: the ledger and boundary gate resolves them before finalize."
            )
        artifacts = enumerate_artifacts(workdir, top)
        return _write_result(status="pass", stage_specific={}, artifacts=artifacts)
    except (OSError, ValueError, SidecarError) as exc:
        print(f"[spec finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
