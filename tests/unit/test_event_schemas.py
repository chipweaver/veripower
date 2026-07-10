import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "framework" / "references" / "schemas" / "events"
EXPECTED = {"dispatch", "outcome", "diagnosis", "escalation", "epoch", "pin", "reopen"}


def test_exactly_seven_event_schemas():
    got = {p.stem.replace(".schema", "") for p in SCHEMA_DIR.glob("*.schema.json")}
    assert got == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_schema_is_valid_and_type_const(name):
    schema = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["type"]["const"] == name
    assert "ts" in schema["required"] and "type" in schema["required"]
