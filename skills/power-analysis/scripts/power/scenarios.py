"""Read the plan's scenario identifiers; execution is authored by power-analysis."""

import json
import re
from pathlib import Path


def load(plan):
    rows = json.loads((Path(plan) / "power-scenarios.json").read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("power-scenarios.json must be a nonempty list")
    ids = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id"}:
            raise ValueError(
                "power scenarios contain only an id; describe them in verification-plan.md"
            )
        sid = row["id"]
        if not isinstance(sid, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*", sid
        ):
            raise ValueError(f"invalid scenario id: {sid!r}")
        if sid in ids:
            raise ValueError(f"duplicate scenario id: {sid}")
        ids.append(sid)
    return ids
