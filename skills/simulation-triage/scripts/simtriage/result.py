"""simtriage.result — schema-gate the analysis judgment, then atomically write result.json.

The judgment is entirely agent-authored: unlike the other stages' finalize scripts there is no
deterministic sidecar to re-derive it from, so `finalize` takes it directly (--json-file /
--json-stdin), validates it against the stage_specific subschema of references/result.schema.json,
and only then wraps it into the envelope and writes it. Validating before the write is the point:
a rejected judgment leaves no file, so the author can fix the content and re-run.

`status` is derived, never agent-supplied — `complete` -> pass, `skipped` -> fail. It is written
because the envelope schema requires it, but nothing routes on it: the reap-time verdict comes
from analysis_state.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

STAGE = "simulation-triage"

_RESULT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "references" / "result.schema.json"
)


def _stage_specific_schema() -> dict:
    """The bare analysis-fields schema, extracted from result.schema.json's stage_specific
    subschema. The agent hands over stage_specific alone, so validating it needs the subschema
    on its own; the whole envelope is re-validated against the same file at reap."""
    doc = json.loads(_RESULT_SCHEMA_PATH.read_text())
    for sub in doc["allOf"]:
        props = sub.get("properties", {})
        if "stage_specific" in props:
            return props["stage_specific"]
    raise ValueError("result.schema.json: no stage_specific subschema found in allOf")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_analysis(payload: dict) -> list[str]:
    """Schema-violation messages (empty list = valid) against the stage_specific contract."""
    errors = sorted(
        Draft202012Validator(_stage_specific_schema()).iter_errors(payload),
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

    Exit 0 = result.json written (status pass or fail, derived from analysis_state).
    Exit 1 = schema violation — nothing written, fix the content and re-run.
    Exit 2 = BLOCKED (unreadable/malformed input JSON, or any internal exception) —
    never conflated with either status.
    """
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

    try:
        errors = validate_analysis(payload)
    except Exception as e:  # noqa: BLE001 — unreadable/malformed schema file
        print(f"validation internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1

    status = "pass" if payload.get("analysis_state") == "complete" else "fail"
    env = {
        "stage": STAGE,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": [],
        "stage_specific": payload,
    }
    try:
        workdir_path = Path(workdir)
        tmp = workdir_path / "result.json.tmp"
        tmp.write_text(json.dumps(env, indent=2) + "\n")
        tmp.replace(workdir_path / "result.json")  # atomic: never observed half-written
    except OSError as e:
        print(f"result.json write error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(
        f"[simtriage finalize] Written: {workdir_path / 'result.json'} (status={status})\n"
    )
    return 0
