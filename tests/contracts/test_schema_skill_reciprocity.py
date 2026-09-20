"""Any generated result field cited by a skill must exist in the schemas.

Stage CLIs construct the envelopes; their generated field inventory need not be in prompts.
"""

import re

import pytest
from skills_source import PLUGIN_ROOT, load_stage_schema

from framework.scripts.rules import FORWARD_PRIORITY


def schema_all_stage_specific_props(stage: str) -> set[str]:
    """Return every property declared under stage_specific (required or not)."""
    schema = load_stage_schema(stage)
    props: set[str] = set()
    for entry in schema.get("allOf", []):
        ss = entry.get("properties", {}).get("stage_specific", {})
        props.update(ss.get("properties", {}).keys())
    return props


def all_known_stage_specific_props() -> set[str]:
    """Union of stage_specific.properties across every stage's schema."""
    seen: set[str] = set()
    for stage in FORWARD_PRIORITY:
        seen.update(schema_all_stage_specific_props(stage))
    return seen


STAGE_SPECIFIC_TOKEN_RE = re.compile(r"stage_specific\.([a-zA-Z_][a-zA-Z0-9_]*)")


@pytest.mark.parametrize("stage", FORWARD_PRIORITY)
def test_skill_stage_specific_tokens_exist_in_schema(stage: str) -> None:
    """Every `stage_specific.X` cited in SKILL.md exists in SOME stage's schema."""
    skill_text = (PLUGIN_ROOT / "skills" / stage / "SKILL.md").read_text(
        encoding="utf-8"
    )
    cited = set(STAGE_SPECIFIC_TOKEN_RE.findall(skill_text))
    if not cited:
        pytest.skip(f"{stage} SKILL.md cites no stage_specific.* tokens")

    known = all_known_stage_specific_props()
    orphans = sorted(cited - known)
    assert not orphans, (
        f"skill {stage}: SKILL.md cites stage_specific.{{{', '.join(orphans)}}} "
        f"but no stage's schema declares them. Either the field was "
        f"renamed/removed and SKILL.md wasn't updated, or the citation is a typo."
    )
