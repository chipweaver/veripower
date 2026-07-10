"""Shared constants for the skill-lint + schema contract tests.

Provides:

- `SKILL_DIRS` — every skill directory name, **derived live** from
  `skills/*/SKILL.md` (the filesystem is the source of truth — this is not a
  hand-maintained list, so it cannot drift and a new skill is auto-covered).
  Used instead of `rules.FORWARD_PRIORITY` because that covers only the 9
  pipeline stages: `design-flow` (the Orchestrator), `simulation-triage` (an
  analysis-only subagent), and `brainstorm` (a pre-pipeline skill) are skills
  without a stage entry and would be missed.

- `PLUGIN_ROOT` — repo root, derived from this file's location.

- `load_stage_schema(stage)` — parse a stage's `result.schema.json`. Shared
  by `tests/unit/` and `tests/contracts/` (both resolve it via the `tests/`
  pythonpath entry).

Private (`_`-prefixed) so pytest won't auto-collect; tests import
explicitly via `from _skills_sot import …`.
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


def load_stage_schema(stage: str) -> dict:
    """Parse skills/<stage>/references/result.schema.json."""
    path = PLUGIN_ROOT / "skills" / stage / "references" / "result.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))
