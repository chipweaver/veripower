"""sim._plan — read the simulation-plan sidecars this stage consumes.

simulation-plan authors the plan as three files; this stage declares and reads `tb-scaffold.json`
and `sequences.json`. They are merged into one dict because that is the shape both the renderer and
the materialization gate walk: `module` from one, `sequences[]` from the other.

Not validated here. simulation-plan schema-validates each when it writes it, and reaching into
another skill's references/ to re-check would couple the two; what can still go wrong at this
point is a missing or unreadable file, which the caller reports.
"""

from __future__ import annotations

import json
from pathlib import Path

SCAFFOLD_NAME = "tb-scaffold.json"
SEQUENCES_NAME = "sequences.json"


def paths(plan_dir) -> tuple[Path, Path]:
    plan_dir = Path(plan_dir)
    return plan_dir / SCAFFOLD_NAME, plan_dir / SEQUENCES_NAME


def load_plan(plan_dir) -> dict:
    """Merged {**tb-scaffold.json, "sequences": sequences.json}."""
    scaffold_path, sequences_path = paths(plan_dir)
    scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
    scaffold["sequences"] = json.loads(sequences_path.read_text(encoding="utf-8"))
    return scaffold
