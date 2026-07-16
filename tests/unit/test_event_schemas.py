import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "framework" / "references" / "schemas" / "events"
EXPECTED = {
    "dispatch",
    "outcome",
    "diagnosis",
    "escalation",
    "pin",
    "reopen",
    "signoff",
}


def test_exactly_seven_event_schemas():
    got = {p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")}
    assert got == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_schema_is_valid_and_type_const(name):
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["type"]["const"] == name
    assert "ts" in schema["required"] and "type" in schema["required"]


def test_outcome_cost_tokens_optional_and_valid():
    """cost_tokens is an optional audit-only object; pre-instrumentation
    outcomes (no cost_tokens) stay valid (backward compat)."""
    schema = json.loads((SCHEMA_DIR / "outcome.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    base = {
        "ts": "2026-07-16T00:00:00Z",
        "type": "outcome",
        "rule": "synthesis",
        "run": 1,
        "verdict": "pass",
        "outputs": {},
        "proofs": [],
        "tool_versions": {},
    }
    assert list(v.iter_errors(base)) == []  # no cost_tokens -> still valid
    with_cost = {
        **base,
        "cost_tokens": {
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 4,
            "total_tokens": 10,
            "message_count": 1,
            "models": ["claude-x"],
            "source": "subagent_trace",
        },
    }
    assert list(v.iter_errors(with_cost)) == []
    assert (
        "cost_tokens" in schema["properties"]
    )  # explicit contract, not just additionalProperties
