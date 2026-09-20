"""Read the functional plan and sequence roster supplied by simulation-plan."""

import json
from pathlib import Path


def load_plan(plan_dir) -> dict:
    plan_dir = Path(plan_dir)
    scaffold = json.loads((plan_dir / "tb-scaffold.json").read_text(encoding="utf-8"))
    scaffold["sequences"] = json.loads(
        (plan_dir / "sequences.json").read_text(encoding="utf-8")
    )
    return scaffold
