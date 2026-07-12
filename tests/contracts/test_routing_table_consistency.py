"""Routing-table drift guard for route.py.

Locks route.py's maps against the schemas / DAG so a drift fails CI:
 - PA_CATEGORY keys == power-analysis failures[].category enum
 - TRIAGE_ROOT_CAUSE keys == simulation-triage ANALYSIS root_cause enum
 - every routed target is a real stage or ESCALATE
 - fixed/triage keys are real stages
"""

import json

from _skills_sot import PLUGIN_ROOT, load_stage_schema

from framework.scripts import rules
from framework.scripts.route import (
    ESCALATE,
    FIXED_TARGET,
    LINT_CATEGORY,
    PA_CATEGORY,
    TRIAGE_ROOT_CAUSE,
)


def _find_enums(node, key):
    """Collect every `enum` list found under a property literally named `key`.

    Recurses into a matched value too (not only non-matches), so a nested scope
    reusing the same property name is also collected — callers assert len()==1,
    so any such ambiguity surfaces as a clear test failure rather than a silent
    wrong-enum match.
    """
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, dict) and "enum" in v:
                out.append(v["enum"])
            out.extend(_find_enums(v, key))
    elif isinstance(node, list):
        for item in node:
            out.extend(_find_enums(item, key))
    return out


def test_pa_category_matches_schema_enum():
    schema = load_stage_schema("power-analysis")
    enums = _find_enums(schema, "category")
    assert len(enums) == 1, f"expected exactly one category enum, found {len(enums)}"
    assert set(PA_CATEGORY) == set(enums[0])


def test_triage_root_cause_matches_analysis_schema_enum():
    schema = json.loads(
        (
            PLUGIN_ROOT
            / "skills"
            / "simulation-triage"
            / "references"
            / "result.schema.json"
        ).read_text(encoding="utf-8")
    )
    enums = _find_enums(schema, "root_cause")
    assert len(enums) == 1, f"expected exactly one root_cause enum, found {len(enums)}"
    assert set(TRIAGE_ROOT_CAUSE) == set(enums[0])


def test_every_target_is_real_stage_or_escalate():
    valid = set(rules.FORWARD_PRIORITY) | {ESCALATE}
    maps = {
        "PA_CATEGORY": PA_CATEGORY,
        "FIXED_TARGET": FIXED_TARGET,
        "LINT_CATEGORY": LINT_CATEGORY,
        "TRIAGE_ROOT_CAUSE": TRIAGE_ROOT_CAUSE,
    }
    for name, m in maps.items():
        for target in m.values():
            assert target in valid, f"{name}: unknown routing target: {target}"


def test_map_keys_are_real_stages():
    stages = set(rules.FORWARD_PRIORITY)
    for key in (*FIXED_TARGET, *TRIAGE_ROOT_CAUSE):
        assert key in stages, f"unknown map key: {key}"
