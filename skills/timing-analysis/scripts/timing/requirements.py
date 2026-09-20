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
COMPARISONS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


def load_requirements(workdir) -> list[dict]:
    """Read and select the requirements judged by this stage."""
    inputs = json.loads((Path(workdir) / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]
    rows = json.loads(
        (Path(inputs["requirements"]) / "requirements.json").read_text(encoding="utf-8")
    )
    ours = [row for row in rows if row["judge"] == STAGE]
    for row in ours:
        if "target" not in row:
            continue
        target = row["target"]
        value = target.get("value")
        if (
            target.get("dim") != "timing_slack_ns"
            or target.get("op") not in COMPARISONS
            or isinstance(value, bool)
            or (not isinstance(value, (int, float)))
            or (not math.isfinite(value))
        ):
            raise ValueError(f"{row['id']}: unsupported timing target {target}")
    return ours


def compare(rows: list[dict], timing: dict) -> list[dict]:
    """Compare report values without turning a rounded VIOLATED zero into a pass."""
    setup, hold = timing["setup"], timing["hold"]
    actual = min(setup["worst_slack_ns"], hold["worst_slack_ns"])
    rounded_violation = actual == 0 and not (setup["met"] and hold["met"])
    return [
        {
            "id": row["id"],
            "actual": actual,
            # VIOLATED supplies the sign lost when the report rounds slack to zero.
            "met": row["target"]["op"] in ("<", "<=")
            if rounded_violation and row["target"]["value"] == 0
            else COMPARISONS[row["target"]["op"]](actual, row["target"]["value"]),
            "measured": "timing-report.txt: minimum worst setup/hold slack (ns); "
            "VIOLATED disambiguates the sign of rounded zero",
        }
        for row in rows
        if "target" in row
    ]


def parse_declared(text: str | None) -> list[dict]:
    """The agent's verdicts for the rows no script compares: [{id, met, measured, actual?}].

    `measured` is refused here rather than at reap: the envelope schema requires it, and a
    verdict that reaches reap without it costs the round a blocked outcome instead of a
    routable one."""
    declared = json.loads(text) if text else []
    for entry in declared:
        if not isinstance(entry.get("id"), str) or not isinstance(
            entry.get("met"), bool
        ):
            raise ValueError(
                f"--requirements entry needs a string id and a boolean met: {entry}"
            )
        if not isinstance(entry.get("measured"), str) or not entry["measured"].strip():
            raise ValueError(
                f"--requirements entry needs `measured` — what you read, and where, so the "
                f"verdict can be checked against the row's own words: {entry}"
            )
    return declared


def merge(rows: list[dict], computed: list[dict], declared: list[dict]) -> list[dict]:
    """One entry per row this stage judges, in ledger order. Raises when a row has no entry or
    an entry names a row this stage does not judge."""
    requirement_ids = [row["id"] for row in rows]
    computed_ids = {entry["id"] for entry in computed}
    if computed_ids & {entry["id"] for entry in declared}:
        raise ValueError("numeric timing targets cannot be overridden by declarations")
    if len({entry["id"] for entry in declared}) != len(declared):
        raise ValueError("duplicate requirement declarations")
    entries = {entry["id"]: entry for entry in computed + declared}
    missing = [i for i in requirement_ids if i not in entries]
    extra = sorted(set(entries) - set(requirement_ids))
    if missing or extra:
        raise ValueError(
            f"requirements judged by {STAGE} are {requirement_ids}; "
            + (f"no verdict for {missing}; " if missing else "")
            + (f"verdicts for rows this stage does not judge: {extra}" if extra else "")
        )
    return [entries[i] for i in requirement_ids]
