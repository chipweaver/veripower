#!/usr/bin/env python3
"""Producer self-gate for the (gating) plan-review.json artifact.

The simulation-plan main thread runs this AFTER assembling the fresh reviewer's findings into
plan-review.json (Step 4) and BEFORE the Step-5 user review loop — fix-and-retry (main-thread
re-assembly, not re-dispatch) on a non-zero exit. Validates against
references/plan-review.schema.json (Draft 2020-12), checks verdict<->findings and
has_critical<->severity consistency, then computes the gate verdict (the mechanical lens x
severity reduction) and prints it as a one-line JSON the main thread copies -- so the gate is
script-owned, not judged by eye.

Gate policy: coverage (testpoint/skip completeness vs spec) findings at critical/important BLOCK
(gate=trip) -- spec is the reference frame. adequacy (check-strategy soundness, no reference) is
advisory must-acknowledge and never blocks; unavailable never blocks.

Usage: validate_plan_review.py <plan-review.json>
Exit: 0 valid (stdout: {"gate","flagged","must_ack"}) / 1 invalid (stderr message).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent / "references" / "plan-review.schema.json"
)

_GATING_LENSES = {"coverage"}
_GATING_SEVERITIES = {"critical", "important"}


def gate_verdict(doc: dict) -> dict:
    """Pure lens x severity reduction over a (schema-valid) plan-review doc.
    coverage at critical/important blocks (gate=trip); adequacy is advisory must-acknowledge;
    unavailable never blocks. Caller guarantees the doc passed the schema/consistency gate
    (main()'s gate, or — for finalize — the on-disk plan-review.json already gated at Step 4)."""
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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_plan_review.py <plan-review.json>", file=sys.stderr)
        return 1
    target = Path(sys.argv[1])
    try:
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        doc = json.loads(target.read_text(encoding="utf-8"))
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
    findings = doc.get("findings", [])
    want_has_critical = any(f.get("severity") == "critical" for f in findings)
    if doc.get("has_critical") != want_has_critical:
        print(
            f"plan-review inconsistent: has_critical={doc.get('has_critical')} "
            f"vs findings-critical={want_has_critical}",
            file=sys.stderr,
        )
        return 1
    want_verdict = (
        "concerns" if any(f.get("lens") != "unavailable" for f in findings) else "ok"
    )
    if doc.get("verdict") != want_verdict:
        print(
            f"plan-review inconsistent: verdict={doc.get('verdict')!r} "
            f"expected {want_verdict!r} from findings",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(gate_verdict(doc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
