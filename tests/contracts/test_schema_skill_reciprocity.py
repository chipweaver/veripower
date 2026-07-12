"""Schema ↔ SKILL.md reciprocity.

Two directions, scoped to catch real drift while staying narrow enough to
avoid false positives on Chinese-mixed SKILL.md text.

**Forward (schema → SKILL)**: Every `stage_specific` field REQUIRED
somewhere in `<stage>/references/result.schema.json` (base required list
or any if/then branch) must be named in the corresponding SKILL.md.
Adding a required field without documenting it leaves the agent unaware.

Optional schema fields (in `properties` but never `required`) are skipped
— `top_module` in rtl-design is an audit-only optional 9a2206c kept
declarable but no longer requires.

**Reverse (SKILL → schema)**: Every `stage_specific.<name>` token cited in
ANY SKILL.md must exist in SOME stage's schema. Checked against the union
of all stage schemas rather than each skill's own — because the SKILL.md
of stage X legitimately cites `stage_specific.violations` etc. when
describing the `{rework_trigger}` channel, which carries another stage's
result.json. Self-citation vs. cross-stage citation isn't recoverable
from text alone without section-aware parsing. The looser bar still
catches "field renamed/removed everywhere" drift — a token that vanished
from every schema continues to be cited in some SKILL.md.
"""

import re

import pytest
from _skills_sot import PLUGIN_ROOT, load_stage_schema

from framework.scripts.rules import FORWARD_PRIORITY


def _schema_required_stage_specific(stage: str) -> set[str]:
    """Return every stage_specific field required by ANY branch (base + if/then)."""
    schema = load_stage_schema(stage)
    required: set[str] = set()

    def _harvest(node: dict) -> None:
        ss = node.get("properties", {}).get("stage_specific", {})
        for field in ss.get("required", []):
            required.add(field)

    for entry in schema.get("allOf", []):
        _harvest(entry)
        if "then" in entry:
            _harvest(entry["then"])
    return required


def _schema_all_stage_specific_props(stage: str) -> set[str]:
    """Return every property declared under stage_specific (required or not)."""
    schema = load_stage_schema(stage)
    props: set[str] = set()
    for entry in schema.get("allOf", []):
        ss = entry.get("properties", {}).get("stage_specific", {})
        props.update(ss.get("properties", {}).keys())
    return props


def _all_known_stage_specific_props() -> set[str]:
    """Union of stage_specific.properties across every stage's schema."""
    seen: set[str] = set()
    for stage in FORWARD_PRIORITY:
        seen.update(_schema_all_stage_specific_props(stage))
    return seen


_STAGE_SPECIFIC_TOKEN_RE = re.compile(r"stage_specific\.([a-zA-Z_][a-zA-Z0-9_]*)")


@pytest.mark.parametrize("stage", FORWARD_PRIORITY)
def test_required_schema_fields_documented_in_skill(stage: str) -> None:
    required_fields = _schema_required_stage_specific(stage)
    if not required_fields:
        pytest.skip(f"{stage} has no required stage_specific fields")

    skill_text = (PLUGIN_ROOT / "skills" / stage / "SKILL.md").read_text(
        encoding="utf-8"
    )
    missing = [f for f in sorted(required_fields) if f not in skill_text]
    assert not missing, (
        f"skill {stage}: schema requires stage_specific.{{{', '.join(missing)}}} "
        f"(per base required[] or an if/then branch) but SKILL.md never names "
        f"them. The agent won't know to populate fields it can't see in its prompt."
    )


@pytest.mark.parametrize("stage", FORWARD_PRIORITY)
def test_skill_stage_specific_tokens_exist_in_schema(stage: str) -> None:
    """Every `stage_specific.X` cited in SKILL.md exists in SOME stage's schema."""
    skill_text = (PLUGIN_ROOT / "skills" / stage / "SKILL.md").read_text(
        encoding="utf-8"
    )
    cited = set(_STAGE_SPECIFIC_TOKEN_RE.findall(skill_text))
    if not cited:
        pytest.skip(f"{stage} SKILL.md cites no stage_specific.* tokens")

    known = _all_known_stage_specific_props()
    orphans = sorted(cited - known)
    assert not orphans, (
        f"skill {stage}: SKILL.md cites stage_specific.{{{', '.join(orphans)}}} "
        f"but no stage's schema declares them. Either the field was "
        f"renamed/removed and SKILL.md wasn't updated, or the citation is a typo."
    )
