"""simtriage.result — schema-gate the analysis judgment, then atomically write result.json.

The judgment is entirely agent-authored: unlike the other stages' finalize scripts there is no
deterministic sidecar to re-derive it from, so `finalize` takes it directly (--json-file /
--json-stdin), validates it against the stage_specific subschema of references/result.schema.json,
and only then wraps it into the envelope and writes it. Validating before the write is the point:
a rejected judgment leaves no file, so the author can fix the content and re-run.

`status=pass` records a completed analysis, including an unresolved attribution with its reason.
Whatever the run built under `{workdir}/experiment/` is enumerated into
`artifacts[]` so the fix owner reaches it through canonical, the way it reaches every other stage's
products.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

STAGE = "simulation-triage"

RESULT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "references" / "result.schema.json"
)


def validate_analysis(payload: dict) -> list[str]:
    """Schema-violation messages (empty list = valid) against the stage_specific contract."""
    result_schema = json.loads(RESULT_SCHEMA_PATH.read_text())
    analysis_schema = next(
        component["properties"]["stage_specific"]
        for component in result_schema["allOf"]
        if "stage_specific" in component.get("properties", {})
    )
    errors = sorted(
        Draft202012Validator(analysis_schema).iter_errors(payload),
        key=lambda e: list(e.absolute_path),
    )
    return [
        f"schema violation at {'/'.join(str(p) for p in e.absolute_path) or '(root)'}: "
        f"{e.message}"
        for e in errors
    ]


def finalize(workdir, json_file, json_stdin) -> int:
    """Validate the analysis judgment (--json-file or piped --json-stdin) against the
    stage_specific contract, then atomically write the full result.json.

    Exit 0 = completed analysis written, with findings or an unresolved reason.
    Exit 1 = schema violation — nothing written, fix the content and re-run.
    Exit 2 = BLOCKED (unreadable/malformed input JSON, or any internal exception) —
    never conflated with either status.
    """
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if json_stdin:
        text = sys.stdin.read()
    else:
        try:
            text = Path(json_file).read_text()
        except OSError as e:
            print(f"--json-file read error: {e}", file=sys.stderr)
            return 2
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"analysis is not valid JSON: {e}", file=sys.stderr)
        return 2

    errors = validate_analysis(payload)
    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1

    env = {
        "stage": STAGE,
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pass",
        "artifacts": (
            [{"path": "experiment"}] if (Path(workdir) / "experiment").is_dir() else []
        ),
        "stage_specific": payload,
    }
    try:
        workdir_path = Path(workdir)
        temporary_path = workdir_path / "result.json.tmp"
        temporary_path.write_text(json.dumps(env, indent=2) + "\n")
        temporary_path.replace(
            workdir_path / "result.json"
        )  # atomic: never observed half-written
    except OSError as e:
        print(f"result.json write error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(
        f"[simtriage finalize] Written: {workdir_path / 'result.json'} (status=pass)\n"
    )
    return 0
