"""The rows of requirements.json this stage establishes, and the envelope entry each one gets.

No row this stage judges can carry a target: it measures no dimension, so `mine` refuses one
that does. Every row it judges is therefore judged by the agent that ran the tool and declared through
`finalize --requirements`. `merge` refuses an envelope that does not account for every row this
stage judges, so a row the agent never read cannot pass as silence.
"""

from __future__ import annotations

import json
from pathlib import Path

STAGE = "lint-cdc"


def load_requirements(workdir) -> list[dict]:
    """Read and select the requirements judged by this stage."""
    inputs = json.loads((Path(workdir) / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]
    rows = json.loads(
        (Path(inputs["requirements"]) / "requirements.json").read_text(encoding="utf-8")
    )
    ours = [row for row in rows if row["judge"] == STAGE]
    bounded = [row["id"] for row in ours if "target" in row]
    if bounded:
        raise ValueError(
            f"{bounded} are judged by {STAGE} and carry a target, but {STAGE} measures no dimension — either the row names the wrong judge, or the bound belongs in a row that judge can compare"
        )
    return ours


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
