"""The rows of requirements.json this stage establishes, and the envelope entry each one gets.

No row this stage judges can carry a target — `check-ledger` refuses a dim lint-cdc does not
compare — so every one of them is judged by the agent that ran the tool and declared through
`finalize --requirements`. `merge` refuses an envelope that does not account for every row this
stage judges, so a row the agent never read cannot pass as silence.
"""

from __future__ import annotations

import json
from pathlib import Path

STAGE = "lint-cdc"


def load(workdir) -> list[dict]:
    """Every row, from the specification root the kernel injected into dispatch.json."""
    inputs = json.loads((Path(workdir) / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]
    return json.loads(
        (Path(inputs["requirements"]) / "requirements.json").read_text(encoding="utf-8")
    )


def mine(rows: list[dict]) -> list[dict]:
    """The rows this stage judges. It compares no dimension, so a row it judges may carry no
    target: there would be no measurement to hold the bound against, and the agent's own
    verdict would stand in for a comparison nobody made."""
    ours = [r for r in rows if r["judge"] == STAGE]
    bounded = [r["id"] for r in ours if "target" in r]
    if bounded:
        raise ValueError(
            f"{bounded} are judged by {STAGE} and carry a target, but {STAGE} measures no "
            f"dimension — either the row names the wrong judge, or the bound belongs in a "
            f"row that judge can compare"
        )
    return ours


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
