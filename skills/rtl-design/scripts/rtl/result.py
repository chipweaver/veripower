"""Validate successful RTL deliveries and retain the evidence of failed work."""

import datetime
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

REFERENCES = Path(__file__).resolve().parents[2] / "references"


class RTLInputError(ValueError):
    """An RTL file list or implementation annotation is missing or invalid."""


def read_rtl_inputs(workdir: Path) -> dict:
    """Validate both input documents and return the ordered compilation inputs."""
    documents = {}
    for filename in ("rtl-files.json", "constraint-annotations.json"):
        path = Path(workdir) / filename
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RTLInputError(f"cannot read {path}: {error}") from error
        schema_path = REFERENCES / f"{path.stem}.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors = sorted(
            Draft202012Validator(schema).iter_errors(document),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            error = errors[0]
            location = "$" + "".join(
                f"[{part!r}]" if isinstance(part, int) else f".{part}"
                for part in error.absolute_path
            )
            raise RTLInputError(
                f"{filename} schema violation at {location}: {error.message}"
            )
        documents[filename] = document
    return documents["rtl-files.json"]


def finalize(workdir, fail_reason=None, fix_owner=None) -> int:
    """Write a pass/fail result; invalid successful-delivery inputs leave no result."""
    workdir = Path(workdir)
    result_path = workdir / "result.json"
    result_path.unlink(missing_ok=True)
    if fail_reason is not None and not fail_reason.strip():
        print("[rtl finalize] BLOCKED: empty --fail-reason", file=sys.stderr)
        return 2
    try:
        if not fail_reason:
            file_list = read_rtl_inputs(workdir)
            missing_sources = [
                filename
                for filename in file_list["files"] + file_list.get("sim_only", [])
                if not (workdir / filename).is_file()
            ]
            if missing_sources:
                raise RTLInputError(
                    "rtl-files.json names files that are not in the workdir: "
                    + ", ".join(missing_sources)
                )
        stage_specific = {"fail_reason": fail_reason} if fail_reason else {}
        if fail_reason and fix_owner:
            stage_specific["fix_owner"] = fix_owner
        result = {
            "stage": "rtl-design",
            "produced_at": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "status": "fail" if fail_reason else "pass",
            "stage_specific": stage_specific,
            "artifacts": [
                {"path": name}
                for name in (
                    "src",
                    "rtl-files.json",
                    "constraint-annotations.json",
                    "semantic-review",
                )
                if (workdir / name).exists()
            ],
        }
        temporary_path = workdir / "result.json.tmp"
        temporary_path.write_text(json.dumps(result, indent=2) + "\n")
        temporary_path.replace(result_path)
        print(f"[rtl finalize] Written: {result_path} (status={result['status']})")
        return 0
    except (OSError, ValueError) as error:
        print(f"[rtl finalize] BLOCKED: {error}", file=sys.stderr)
        return 2
