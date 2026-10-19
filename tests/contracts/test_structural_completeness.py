"""Structural completeness per stage / skill.

Forward stages in `rules.FORWARD_PRIORITY` must provide:

  - skills/<name>/SKILL.md
  - skills/<name>/references/result.schema.json
  - a `rules.RULES` entry with its `workdir_root`  (stages only; covered by
    tests/unit/test_rules.py)

Other skills are discovered by `skills_source` and checked for SKILL.md.
This group includes simulation-triage, a diagnostic stage that submits result.json.

These tests turn the SKILL.md / schema runtime failures (`dispatch` from a
missing skill, schema 404 inside `validate_result`) into clear unit-test
diagnostics naming the exact path that's missing.
"""

import pytest
from skills_source import PLUGIN_ROOT, SKILL_DIRS

from framework.scripts.rules import FORWARD_PRIORITY

OTHER_SKILLS: list[str] = sorted(set(SKILL_DIRS) - set(FORWARD_PRIORITY))


def test_skill_dirs_is_superset_of_forward_priority() -> None:
    """A stage cannot enter the pipeline without a corresponding skill dir."""
    missing = set(FORWARD_PRIORITY) - set(SKILL_DIRS)
    assert not missing, (
        f"rules.FORWARD_PRIORITY contains {sorted(missing)} but skills_source."
        f"SKILL_DIRS does not. Add skills/<stage>/SKILL.md so skill discovery "
        f"and the contract checks can find the stage(s)."
    )


# ── stages: SKILL.md + result.schema.json required ─────────────────────


@pytest.mark.parametrize("stage", FORWARD_PRIORITY)
def test_stage_has_skill_md(stage: str) -> None:
    p = PLUGIN_ROOT / "skills" / stage / "SKILL.md"
    assert p.is_file(), (
        f"FORWARD_PRIORITY lists {stage!r} but {p.relative_to(PLUGIN_ROOT)} "
        f"is missing. Orchestrator cannot dispatch this stage without a SKILL.md."
    )


@pytest.mark.parametrize("stage", FORWARD_PRIORITY)
def test_stage_has_result_schema(stage: str) -> None:
    p = PLUGIN_ROOT / "skills" / stage / "references" / "result.schema.json"
    assert p.is_file(), (
        f"FORWARD_PRIORITY lists {stage!r} but {p.relative_to(PLUGIN_ROOT)} "
        f"is missing. store.validate_result cannot resolve a schema at reap time."
    )


# ── other skills: SKILL.md required ────────────────────────────────────


@pytest.mark.parametrize("skill", OTHER_SKILLS)
def test_other_skill_has_skill_md(skill: str) -> None:
    p = PLUGIN_ROOT / "skills" / skill / "SKILL.md"
    assert p.is_file(), (
        f"SKILL_DIRS lists {skill!r} but {p.relative_to(PLUGIN_ROOT)} is missing"
    )
