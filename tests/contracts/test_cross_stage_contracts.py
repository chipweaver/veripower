"""Cross-stage producer/consumer contract checks.

Invariants that prevent silent-transformation drift across stage boundaries:

3. **Judge namespace.** The ledger's `judge` enum is the rule registry's
   FORWARD_PRIORITY plus the three non-stage judges and the transient
   `unassignable`; a stage added to rules.py without the enum is caught here.

2. **result.json path consistency.** Every `(Design|Verification)/<stage>/
   result.json` reference in any SKILL.md must match the stage's canonical
   `rules.RULES[stage].workdir_root`. A SKILL.md saying `Design/synthesis/`
   while the kernel promotes to `Verification/synthesis/` is the canonical
   path-drift incident type the failure-memory entry flags.
"""

import json
import re

import pytest
from skills_source import PLUGIN_ROOT

from framework.scripts import rules
from framework.scripts.rules import FORWARD_PRIORITY

# stage -> canonical workdir_root tuple (the kernel-era (dir, stage) mapping,
# derived live from rules.RULES).
RESULT_DIR = {name: r.workdir_root for name, r in rules.RULES.items()}


def collect_dim_values_from_array_schema(array_schema: dict) -> set[str]:
    """Pull const/enum dim values out of an `items.properties.dim` slot.

    Returns an empty set for pattern-based dim definitions (e.g.
    timing-analysis violations use `pattern: ^timing_…$` which is a
    different namespace from PPA gate dims and shouldn't be checked
    against the ledger's bounds).
    """
    dim_schema = array_schema.get("items", {}).get("properties", {}).get("dim", {})
    if "const" in dim_schema:
        return {dim_schema["const"]}
    if "enum" in dim_schema:
        return set(dim_schema["enum"])
    return set()


def ledger_schema() -> dict:
    return json.loads(
        (
            PLUGIN_ROOT
            / "skills"
            / "specification"
            / "references"
            / "requirements.schema.json"
        ).read_text(encoding="utf-8")
    )


def test_judge_enum_is_the_rule_registry_plus_the_non_stage_judges() -> None:
    judges = ledger_schema()["items"]["properties"]["judge"]["enum"]
    assert judges == [*FORWARD_PRIORITY, "human", "outside", "none", "unassignable"]


RESULT_PATH_RE = re.compile(r"\b(Design|Verification)/([a-z][a-z0-9-]*)/result\.json\b")


@pytest.mark.parametrize("skill_name", FORWARD_PRIORITY)
def test_result_path_references_match_state_dir(skill_name: str) -> None:
    """In each SKILL.md, every Design|Verification/<stage>/result.json
    citation must use the dir prefix rules.RULES[stage].workdir_root maps.
    """
    skill_md = PLUGIN_ROOT / "skills" / skill_name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    drifts: list[tuple[str, str, str]] = []
    for m in RESULT_PATH_RE.finditer(text):
        cited_dir, cited_stage = m.group(1), m.group(2)
        expected = RESULT_DIR.get(cited_stage)
        if expected is None:
            drifts.append((cited_stage, cited_dir, "<unknown stage>"))
            continue
        if expected[0] != cited_dir:
            drifts.append((cited_stage, cited_dir, expected[0]))

    assert not drifts, f"SKILL.md {skill_name}: result.json path drift — " + "; ".join(
        f"cites {d}/{s}/result.json but rules.workdir_root says {e}/{s}"
        for s, d, e in drifts
    )
