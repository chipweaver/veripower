"""The rows of requirements.json this stage establishes, and the envelope entry each one gets.

A row with a target is judged by this stage's script against the number it parsed; a row without
one is judged by the agent that ran the tool and declared through `finalize --requirements`.
`merge` refuses an envelope that does not account for every row this stage judges, so a row the
agent never read cannot pass as silence.
"""

from __future__ import annotations

import json
import operator
from pathlib import Path

STAGE = "power-analysis"
_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


def load(workdir) -> list[dict]:
    """Every row, from the specification root the kernel injected into dispatch.json."""
    inputs = json.loads((Path(workdir) / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]
    return json.loads(
        (Path(inputs["requirements"]) / "requirements.json").read_text(encoding="utf-8")
    )


def mine(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["judge"] == STAGE]


def met(actual: float, target: dict) -> bool:
    return _OPS[target["op"]](actual, target["value"])


def parse_declared(text: str | None) -> list[dict]:
    """The agent's verdicts for the rows no script compares: [{id, met, actual?}]."""
    declared = json.loads(text) if text else []
    for e in declared:
        if not isinstance(e.get("id"), str) or not isinstance(e.get("met"), bool):
            raise ValueError(
                f"--requirements entry needs a string id and a boolean met: {e}"
            )
    return declared


def merge(rows: list[dict], computed: list[dict], declared: list[dict]) -> list[dict]:
    """One entry per row this stage judges, in ledger order. Raises when a row has no entry or
    an entry names a row this stage does not judge."""
    ids = [r["id"] for r in rows]
    entries = {e["id"]: e for e in computed + declared}
    missing = [i for i in ids if i not in entries]
    extra = sorted(set(entries) - set(ids))
    if missing or extra:
        raise ValueError(
            f"requirements judged by {STAGE} are {ids}; "
            + (f"no verdict for {missing}; " if missing else "")
            + (f"verdicts for rows this stage does not judge: {extra}" if extra else "")
        )
    return [entries[i] for i in ids]


def unmet(entries: list[dict]) -> list[str]:
    return [e["id"] for e in entries if not e["met"]]
