"""The rows of requirements.json this stage establishes, and the envelope entry each one gets.

Numeric timing_slack_ns targets compare the worst setup/hold slack from PrimeTime.
Other rows are judged by the agent through `finalize --requirements`.
"""

from __future__ import annotations

import json
import math
import operator
from pathlib import Path

STAGE = "timing-analysis"
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
    """Select this stage's rows and reject unsupported numeric targets."""
    ours = [r for r in rows if r["judge"] == STAGE]
    for row in ours:
        if "target" not in row:
            continue
        t = row["target"]
        value = t.get("value")
        if (
            t.get("dim") != "timing_slack_ns"
            or t.get("op") not in _OPS
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{row['id']}: unsupported timing target {t}")
    return ours


def compare(rows: list[dict], timing: dict) -> list[dict]:
    """Compare report values without turning a rounded VIOLATED zero into a pass."""
    setup, hold = timing["setup"], timing["hold"]
    actual = min(setup["worst_slack_ns"], hold["worst_slack_ns"])
    rounded_violation = actual == 0 and not (setup["met"] and hold["met"])
    return [
        {
            "id": r["id"],
            "actual": actual,
            # VIOLATED supplies the sign lost when the report rounds slack to zero.
            "met": r["target"]["op"] in ("<", "<=")
            if rounded_violation and r["target"]["value"] == 0
            else _OPS[r["target"]["op"]](actual, r["target"]["value"]),
            "measured": "timing-report.txt: minimum worst setup/hold slack (ns); "
            "VIOLATED disambiguates the sign of rounded zero",
        }
        for r in rows
        if "target" in r
    ]


def parse_declared(text: str | None) -> list[dict]:
    """The agent's verdicts for the rows no script compares: [{id, met, measured, actual?}].

    `measured` is refused here rather than at reap: the envelope schema requires it, and a
    verdict that reaches reap without it costs the round a blocked outcome instead of a
    routable one."""
    declared = json.loads(text) if text else []
    for e in declared:
        if not isinstance(e.get("id"), str) or not isinstance(e.get("met"), bool):
            raise ValueError(
                f"--requirements entry needs a string id and a boolean met: {e}"
            )
        if not isinstance(e.get("measured"), str) or not e["measured"].strip():
            raise ValueError(
                f"--requirements entry needs `measured` — what you read, and where, so the "
                f"verdict can be checked against the row's own words: {e}"
            )
    return declared


def merge(rows: list[dict], computed: list[dict], declared: list[dict]) -> list[dict]:
    """One entry per row this stage judges, in ledger order. Raises when a row has no entry or
    an entry names a row this stage does not judge."""
    ids = [r["id"] for r in rows]
    computed_ids = {e["id"] for e in computed}
    if computed_ids & {e["id"] for e in declared}:
        raise ValueError("numeric timing targets cannot be overridden by declarations")
    if len({e["id"] for e in declared}) != len(declared):
        raise ValueError("duplicate requirement declarations")
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
