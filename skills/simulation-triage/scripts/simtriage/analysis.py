"""Producer self-gate for the simulation-triage ANALYSIS routing block — the validate-analysis verb.

Validates a JSON payload (--json-file or piped --json-stdin) against analysis.schema.json
(Draft 2020-12). Exit 0 = valid; exit 1 = invalid (formatted error on stderr). Writes no
files itself — simulation-triage lands analysis.json under its own canonical read-only +
scratch-writable Iron Rule (SKILL.md), and runs this validator as the pre-publish gate
before that write, fixing and rerunning on failure (mirrors simplan validate-review).

--schema is an optional override; the main path uses the packaged sibling
references/analysis.schema.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_DEFAULT_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "analysis.schema.json"
)


def validate(json_file, json_stdin, schema) -> int:
    if json_stdin:
        text = sys.stdin.read()
    else:
        try:
            text = Path(json_file).read_text()
        except OSError as e:
            print(f"--json-file read error: {e}", file=sys.stderr)
            return 1
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"ANALYSIS is not valid JSON: {e}", file=sys.stderr)
        return 1

    schema_path = Path(schema) if schema else _DEFAULT_SCHEMA
    try:
        schema_doc = json.loads(schema_path.read_text())
        errors = sorted(
            Draft202012Validator(schema_doc).iter_errors(payload),
            key=lambda e: list(e.absolute_path),
        )
    except Exception as e:  # malformed schema / library failure
        print(f"validation internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if errors:
        for e in errors:
            loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
            print(f"schema violation at {loc}: {e.message}", file=sys.stderr)
        return 1
    return 0
