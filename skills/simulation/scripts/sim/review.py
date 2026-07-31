#!/usr/bin/env python3
"""sim validate-review — schema + gate verdict over the conformance reviewer's own record.

The reviewer Task writes conformance-review.json; this validates that file against
references/conformance-review.schema.json (Draft 2020-12) and prints the gate verdict as one
JSON line, so the trip/clear call is script-owned rather than judged by eye. `compute_gate` is
reused in-process by the finalize verb (sim.result), which re-runs it before writing a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "conformance-review.schema.json"
)


def compute_gate(doc: dict) -> dict:
    """The gate verdict: any finding the reviewer called blocking stops the round.

    There is nothing to reduce beyond that. A taxonomy here would only re-derive a call the
    reviewer already made, in a vocabulary it had to be taught first. No schema checks
    (validate() runs those first; finalize calls this over the on-disk doc)."""
    blocking = [f for f in doc.get("findings", []) if f.get("blocking")]
    return {
        "gate": "trip" if blocking else "clear",
        "flagged": sorted({f.get("tp_id") for f in blocking if f.get("tp_id")}),
    }


def validate(review_path) -> int:
    target = Path(review_path)
    try:
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"conformance-review validate: cannot read {target} or schema: {e}",
            file=sys.stderr,
        )
        return 1
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path)
    )
    if errors:
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(
                f"conformance-review invalid at {loc}: {err.message}", file=sys.stderr
            )
        return 1
    print(json.dumps(compute_gate(doc)))
    return 0
