"""requirements.json — the ledger of what the engineer's intent document requires.

One row per proposition, in the engineer's words, with `judge` naming who establishes it. Scripts
act on `id`, `judge` and `target` only; `verbatim` and `note` are text they carry through. This
module holds the two readings scripts need: which rows check-hints must name, and the rows a human
must see verbatim at the Wave 1 gate.
"""

import json

from spec.sidecar import read_sidecar

NAME = "requirements.json"

# Rows the Wave 1 gate shows verbatim: what the author could not place, what the pipeline does
# not judge, what a person judges, and the numbers scripts will gate on with no later review.
GATE_JUDGES = ("unassignable", "outside", "human")


def load(workdir) -> list[dict]:
    return read_sidecar(workdir, NAME)


def hintable_ids(rows: list[dict]) -> set[str]:
    """Rows a check-hint must name: judged by simulation, with no coverage target."""
    return {r["id"] for r in rows if r["judge"] == "simulation" and "target" not in r}


def gate_view(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["judge"]] = counts.get(r["judge"], 0) + 1
    groups = {j: [r for r in rows if r["judge"] == j] for j in GATE_JUDGES}
    groups["target"] = [r for r in rows if "target" in r]
    return {"rows": len(rows), "by_judge": counts, "verbatim": groups}


def run(workdir: str) -> int:
    """check-ledger: validate requirements.json and print what the Wave 1 gate hands the human."""
    rows = load(workdir)  # raises SidecarError naming every violation
    print(json.dumps(gate_view(rows), ensure_ascii=False, indent=2))
    return 0


def unassignable(rows: list[dict]) -> list[str]:
    return [r["id"] for r in rows if r["judge"] == "unassignable"]
