"""Shared requirement identifiers and decision-facing ledger views.

Scripts select obligations by id, judge and target; readers interpret source wording and notes.
"""

import json

from spec.sidecar import read_sidecar

# Decision-facing groups; numerical targets are included separately.
GATE_JUDGES = ("unassignable", "outside", "human")


def gate_view(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["judge"]] = counts.get(r["judge"], 0) + 1
    groups = {j: [r for r in rows if r["judge"] == j] for j in GATE_JUDGES}
    groups["target"] = [r for r in rows if "target" in r]
    return {"rows": len(rows), "by_judge": counts, "verbatim": groups}


def run(workdir: str) -> int:
    """Validate the ledger and show unresolved decisions, external scope and targets."""
    rows = read_sidecar(
        workdir, "requirements.json"
    )  # raises SidecarError naming every violation
    print(json.dumps(gate_view(rows), ensure_ascii=False, indent=2))
    return 0
