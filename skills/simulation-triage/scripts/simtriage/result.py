"""simtriage.result — schema-gate the analysis judgment, then atomically write result.json.

Task C7: simulation-triage is now an ordinary kernel-scheduled rule (rules.py: proof=None) —
the old runs/<sim_run>/analysis.json + top-level analysis.json pointer double-file mechanism
is retired; the single output surface is Verification/simulation-triage/runs/<N>/result.json
(kernel-issued workdir, atomic temp+rename per Task C1).

The routing (analysis_state/root_cause/confidence) + advisory (level/fix_direction/findings/
waveform/experiment) judgment is entirely agent-authored — there is no deterministic sidecar
to re-derive it from, unlike the other stages' finalize scripts. `finalize` therefore takes
that judgment directly (--json-file/--json-stdin, same shape the old analysis.json carried),
schema-gates it against the stage_specific subschema folded into references/result.schema.json
(single source of truth — the standalone analysis.schema.json is deleted), and on success wraps
it into the full envelope and writes it. `status` is derived, never agent-supplied: `complete`
(a landed verdict, including a self-pointing root_cause=simulation) -> pass; `skipped` -> fail.
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
    """The bare analysis-fields schema, extracted from the merged result.schema.json's
    stage_specific subschema (single source of truth — Task C7 folded the old standalone
    analysis.schema.json in here)."""
    doc = json.loads(_RESULT_SCHEMA_PATH.read_text())
    for sub in doc["allOf"]:
        props = sub.get("properties", {})
        if "stage_specific" in props:
            return props["stage_specific"]
    raise ValueError("result.schema.json: no stage_specific subschema found in allOf")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_analysis(payload: dict, schema: dict | None = None) -> list[str]:
    """Schema-violation messages (empty list = valid) against the stage_specific
    contract, or an explicit override schema."""
    schema_doc = schema if schema is not None else _stage_specific_schema()
    errors = sorted(
        Draft202012Validator(schema_doc).iter_errors(payload),
        key=lambda e: list(e.absolute_path),
    )
    return [
        f"schema violation at {'/'.join(str(p) for p in e.absolute_path) or '(root)'}: "
        f"{e.message}"
        for e in errors
    ]


def finalize(workdir, module, json_file, json_stdin, schema_override) -> int:
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

    schema_doc = None
    if schema_override is not None:
        try:
            schema_doc = json.loads(Path(schema_override).read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"--schema read/parse error: {e}", file=sys.stderr)
            return 2

    try:
        errors = validate_analysis(payload, schema_doc)
    except Exception as e:  # noqa: BLE001 — malformed schema / library failure
        print(f"validation internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1

    status = "pass" if payload.get("analysis_state") == "complete" else "fail"
    env = {
        "schema_version": 1,
        "stage": STAGE,
        "module": module,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": [],
        "stage_specific": payload,
    }
    try:
        workdir_path = Path(workdir)
        tmp = workdir_path / "result.json.tmp"
        tmp.write_text(json.dumps(env, indent=2) + "\n")
        tmp.replace(
            workdir_path / "result.json"
        )  # atomic: never observed half-written
    except OSError as e:
        print(f"result.json write error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(
        f"[simtriage finalize] Written: {workdir_path / 'result.json'} (status={status})\n"
    )
    return 0
