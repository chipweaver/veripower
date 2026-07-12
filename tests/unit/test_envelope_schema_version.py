"""schema_version lives in the envelope (single source), not per-stage.

Until 2026-06-19 the R1 completion-certificate version `schema_version` was
pinned in nine places — each `skills/<stage>/references/result.schema.json`
carried its own `{"const": 1}` + `required: ["schema_version", ...]`. The
common `envelope.schema.json` (which `result-schema-design.md` calls the home
of the universal R1 fields) was the one R1 field it omitted.

It now lives in the envelope: the per-stage schemas inherit it via `$ref`, a
uniform bump (1 -> 2) is a one-line change, and there is a single source of
truth. These tests lock that:
  1. the envelope requires + pins `schema_version`;
  2. no per-stage schema re-pins it (single source);
  3. presence + `const 1` are enforced through the envelope for every stage.
"""

import json

import pytest
from _skills_sot import PLUGIN_ROOT, load_stage_schema

from framework.scripts import facts, rules

_ENVELOPE = (
    PLUGIN_ROOT / "framework" / "references" / "schemas" / "envelope.schema.json"
)

_FAILURE_KIND_STAGES = {"synthesis", "timing-analysis", "power-analysis"}
_FAILURE_PHASE_STAGES = {"simulation"}


def test_envelope_requires_and_pins_schema_version():
    env = json.loads(_ENVELOPE.read_text(encoding="utf-8"))
    assert "schema_version" in env["required"]
    assert env["properties"]["schema_version"] == {"const": 1}


def _repins_schema_version(node) -> bool:
    """True if any subschema re-declares schema_version as a property or requires it."""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict) and "schema_version" in props:
            return True
        req = node.get("required")
        if isinstance(req, list) and "schema_version" in req:
            return True
        return any(_repins_schema_version(v) for v in node.values())
    if isinstance(node, list):
        return any(_repins_schema_version(v) for v in node)
    return False


@pytest.mark.parametrize("stage", rules.FORWARD_PRIORITY)
def test_per_stage_schema_does_not_repin_schema_version(stage):
    # Single source of truth: schema_version is inherited from the envelope,
    # never re-pinned (property) or re-required in a per-stage schema.
    assert not _repins_schema_version(load_stage_schema(stage)), (
        f"{stage}: schema_version is re-pinned per-stage; it must be inherited "
        "from envelope.schema.json (single source)"
    )


@pytest.mark.parametrize("stage", rules.FORWARD_PRIORITY)
def test_schema_version_enforced_via_envelope(stage):
    stage_specific = {"fail_reason": "test fail"}
    if stage in _FAILURE_KIND_STAGES:
        stage_specific["failure_kind"] = "infra"
    if stage in _FAILURE_PHASE_STAGES:
        stage_specific["failure_phase"] = "compile"

    base = {
        "stage": stage,
        "module": "M",
        "produced_at": "2026-06-19T00:00:00Z",
        "status": "fail",
        "artifacts": [],
        "stage_specific": stage_specific,
    }

    # Missing schema_version -> rejected (now enforced by the envelope).
    assert facts.validate_result(stage, base) is not None, (
        f"{stage}: result.json without schema_version accepted"
    )

    # Wrong schema_version -> rejected (const 1).
    assert facts.validate_result(stage, {"schema_version": 2, **base}) is not None, (
        f"{stage}: schema_version=2 accepted"
    )

    # schema_version: 1 -> accepted.
    err = facts.validate_result(stage, {"schema_version": 1, **base})
    assert err is None, f"{stage}: valid envelope with schema_version=1 rejected: {err}"
