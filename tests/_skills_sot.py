"""Shared constants for the skill-lint + state-machine test trio.

Provides, for the skill-lint + state-machine tests:

- `SKILL_DIRS` — every skill directory name, **derived live** from
  `skills/*/SKILL.md` (the filesystem is the source of truth — this is not a
  hand-maintained list, so it cannot drift and a new skill is auto-covered).
  Used instead of `state.FORWARD_PRIORITY` because that covers only the 9
  pipeline stages: `design-flow` (the Orchestrator), `simulation-triage` (an
  analysis-only subagent), and `brainstorm` (a pre-pipeline skill) are skills
  without a stage entry and would be missed.

- `STAGE_SPECIFIC_MINIMAL` — minimum `stage_specific` payloads that satisfy
  each per-stage `result.schema.json`. Consumed by
  `test_state.TestCmdComplete / TestFullLoop` and
  `test_dispatcher_trigger_invariant` to drive cmd_reap pass paths.

- `PLUGIN_ROOT` — repo root, derived from this file's location.

- `load_stage_schema(stage)` — parse a stage's `result.schema.json`. Shared
  by `tests/unit/` and `tests/contracts/` (both resolve it via the `tests/`
  pythonpath entry).

Private (`_`-prefixed) so pytest won't auto-collect; tests import
explicitly via `from _skills_sot import …`. Distinct from `conftest.py`
(which carries test helpers); this module is the constants-and-schema-loader sibling.
"""

import json
from pathlib import Path

PLUGIN_ROOT: Path = Path(__file__).resolve().parents[1]

# Derived live from the filesystem (the source of truth) — every skills/<name>/
# with a SKILL.md. Not a hand-maintained list: a new skill is auto-covered by
# the contract lints, and there is nothing to drift.
SKILL_DIRS: list[str] = sorted(
    d.name for d in (PLUGIN_ROOT / "skills").iterdir() if (d / "SKILL.md").is_file()
)

STAGE_SPECIFIC_MINIMAL: dict[str, dict] = {
    "specification": {"top_module": "M", "ppa_targets": []},
    "simulation-plan": {},
    "rtl-design": {},
    "lint-cdc": {"violations": []},
    "simulation": {},
    "synthesis": {
        "ppa_actual": [{"dim": "area_um2", "value": 1000.0}],
    },
    "timing-analysis": {
        "violations": [],
        "timing": {
            "setup": {"worst_slack_ns": 0.0, "met": True, "worst_path": "a -> b"},
            "hold": {"worst_slack_ns": 0.0, "met": True, "worst_path": "c -> d"},
            "coverage": {
                "unconstrained_max_delay_endpoints": 0,
                "register_pins_no_clock": 0,
            },
        },
    },
    "power-analysis": {
        "ppa_actual": [{"dim": "power_mw", "value": 1.0, "scenario_id": "S1"}],
        "power_by_corner": [
            {
                "scenario_id": "S1",
                "power_mw": 1.0,
                "corner_intent": "TT",
                "sequence_ref": "test_a",
            }
        ],
    },
    "frontend-signoff": {},
}


def load_stage_schema(stage: str) -> dict:
    """Parse skills/<stage>/references/result.schema.json."""
    path = PLUGIN_ROOT / "skills" / stage / "references" / "result.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))
