#!/usr/bin/env python3
"""sim validate-review — the gate verdict over the conformance reviewer's own record.

The reviewer writes conformance-review.md; this reads the one thing a machine takes out of it
and prints it as a JSON line. That keeps the trip/clear call out of the main thread's hands,
which matters because nothing human reads this record before the stage routes on it and the
main thread's own status is what the call decides.

One heading per finding, and a blocking one says so:

    ## TP-03  tb/uvm/checker/m_scoreboard.sv:49  BLOCKING
    <prose: what the check does, what the intent asked for, where they part>

Nothing parses the prose. `compute_gate` is reused in-process by the finalize verb
(sim.result), which re-runs it before writing a pass.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# A finding heading. The id is the first token after the hashes and the marker is the last, so
# a location carrying spaces still parses.
_HEADING = re.compile(r"^##\s+(?P<tp_id>\S+)\s+(?P<rest>.*?)\s*$")
_BLOCKING = "BLOCKING"


def compute_gate(text: str) -> dict:
    """The gate verdict: any finding the reviewer marked BLOCKING stops the round.

    There is nothing else to reduce. A field set or a severity word here would only re-encode
    a call the reviewer already made, in a vocabulary it had to be taught first."""
    flagged = [
        m.group("tp_id")
        for m in (_HEADING.match(ln) for ln in text.splitlines())
        if m and m.group("rest").split()[-1:] == [_BLOCKING]
    ]
    return {"gate": "trip" if flagged else "clear", "flagged": sorted(set(flagged))}


def validate(review_path) -> int:
    target = Path(review_path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as e:
        print(f"conformance-review: cannot read {target}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(compute_gate(text)))
    return 0
