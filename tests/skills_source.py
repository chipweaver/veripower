"""Shared skill discovery and schema loading for regression tests.

SKILL_DIRS comes from installed skill directories rather than the stage registry,
so non-stage skills are checked too. PLUGIN_ROOT is relative to this file.
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
