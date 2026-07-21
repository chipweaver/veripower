"""Producer self-gate for the (gating) plan-review.json artifact — the validate-review verb.

The simulation-plan main thread runs this AFTER assembling the fresh reviewer's findings into
plan-review.json (the plan-adequacy review) and BEFORE the user review loop — fix-and-retry (main-thread
re-assembly, not re-dispatch) on a non-zero exit. Validates against
references/plan-review.schema.json (Draft 2020-12), then computes the gate verdict (the mechanical lens x
severity reduction) and prints it as a one-line JSON -- so the gate is
script-owned, not judged by eye.

Gate policy: coverage (testpoint/skip completeness vs spec) findings at critical/important BLOCK
(gate=trip) -- spec is the reference frame. adequacy (check-strategy soundness, no reference) is
advisory must-acknowledge and never blocks; unavailable never blocks.

gate_verdict is a pure public function: result.build_result imports it in-process for the
finalize status derivation, so it must NOT touch the schema or do I/O.

Exit: 0 valid (stdout: {"gate","flagged","must_ack"}) / 1 invalid (stderr message).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "plan-review.schema.json"
)

_GATING_LENSES = {"coverage"}
_GATING_SEVERITIES = {"critical", "important"}


def gate_verdict(doc: dict) -> dict:
    """Pure lens x severity reduction over a (schema-valid) plan-review doc.
    coverage at critical/important blocks (gate=trip); adequacy is advisory must-acknowledge;
    unavailable never blocks. Caller guarantees the doc passed the schema gate
    (validate()'s gate, or — for finalize — the on-disk plan-review.json already gated by the plan-adequacy review)."""
    findings = doc.get("findings", [])
    gating = [
        f
        for f in findings
        if f.get("lens") in _GATING_LENSES and f.get("severity") in _GATING_SEVERITIES
    ]
    flagged = [
        {"tp_id": f.get("tp_id"), "lens": f.get("lens"), "severity": f.get("severity")}
        for f in sorted(gating, key=lambda f: (f.get("tp_id", ""), f.get("lens", "")))
    ]
    must_ack = [
        {"tp_id": f.get("tp_id"), "severity": f.get("severity")}
        for f in sorted(
            (f for f in findings if f.get("lens") == "adequacy"),
            key=lambda f: (f.get("tp_id", ""), f.get("severity", "")),
        )
    ]
    return {
        "gate": "trip" if gating else "clear",
        "flagged": flagged,
        "must_ack": must_ack,
    }


def validate(target: Path) -> int:
    try:
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        doc = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"plan-review validate: cannot read {target} or schema: {e}",
            file=sys.stderr,
        )
        return 1
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path)
    )
    if errors:
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(f"plan-review invalid at {loc}: {err.message}", file=sys.stderr)
        return 1
    print(json.dumps(gate_verdict(doc)))
    return 0
