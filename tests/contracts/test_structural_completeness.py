"""Structural completeness per stage / skill.

When a stage is added to `rules.FORWARD_PRIORITY` (or a non-stage skill is
added to `SKILL_DIRS`), the surrounding surfaces must come with it:

  - skills/<name>/SKILL.md
  - skills/<name>/references/result.schema.json  (stages only — non-stage
    skills like design-flow / simulation-triage produce no result.json)
  - a `rules.RULES` entry with its `workdir_root`  (stages only; covered by
    tests/unit/test_rules.py)

These tests turn the SKILL.md / schema runtime failures (`dispatch` from a
missing skill, schema 404 inside `validate_result`) into clear unit-test
diagnostics naming the exact path that's missing.

**Scenarios are NOT required per skill.** After the 2026-06-10 scenario
re-grounding, `tests/scenarios/<name>/` is deliberately lean: a skill earns a
scenario only when an invariant robustly fails a clean RED baseline (most don't,
on Opus — see `tests/scenarios/README.md`). An empty per-skill scenario dir is
the honest outcome, not a structural gap — so there is no "stage has scenarios"
presence contract.
"""

import pytest
from _skills_sot import PLUGIN_ROOT, SKILL_DIRS

from framework.scripts.rules import FORWARD_PRIORITY

_NON_STAGE_SKILLS: list[str] = sorted(set(SKILL_DIRS) - set(FORWARD_PRIORITY))


def test_skill_dirs_is_superset_of_forward_priority() -> None:
    """A stage cannot enter the pipeline without a corresponding skill dir."""
    missing = set(FORWARD_PRIORITY) - set(SKILL_DIRS)
    assert not missing, (
        f"rules.FORWARD_PRIORITY contains {sorted(missing)} but _skills_sot."
        f"SKILL_DIRS does not. Add the stage(s) to SKILL_DIRS so the contract "
        f"lints in tests/contracts/ cover them."
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
        f"is missing. facts.validate_result cannot resolve a schema at reap time."
    )


# ── non-stage skills (design-flow, simulation-triage): SKILL.md required ──


@pytest.mark.parametrize("skill", _NON_STAGE_SKILLS)
def test_non_stage_skill_has_skill_md(skill: str) -> None:
    p = PLUGIN_ROOT / "skills" / skill / "SKILL.md"
    assert p.is_file(), (
        f"SKILL_DIRS lists {skill!r} but {p.relative_to(PLUGIN_ROOT)} is missing"
    )
