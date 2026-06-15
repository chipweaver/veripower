#!/usr/bin/env python3
"""Producer self-gate for the conformance-review.json artifact.

The simulation main thread runs this AFTER assembling the reviewer's findings into
conformance-review.json and BEFORE listing it in artifacts[] / making the gate
decision — fix-and-retry (main-thread re-assembly, not re-dispatch) on a non-zero exit.
Validates the file against references/conformance-review.schema.json (Draft 2020-12),
checks verdict<->findings and has_critical<->severity consistency, then computes the gate
verdict (the mechanical category x severity reduction over the findings) and prints it as a
one-line JSON the main thread copies -- so the gate is script-owned, not judged by eye.

Usage: validate_conformance_review.py <conformance-review.json>
Exit: 0 valid (stdout: {"gate","flagged","dominant_category"}) / 1 invalid (stderr message).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "conformance-review.schema.json"
)

# Gate policy: a finding gates (status=fail) iff its category is a gating class AND its
# severity is critical/important. Advisory categories (unverifiable-arch, unavailable) and
# minor severity never gate. This is the schema-bound mechanical reduction over the reviewer's
# findings -- owned here, not applied by eye in SKILL.md.
_GATING_CATEGORIES = {"missing", "wrong-behavior", "fake-green", "intent-defect"}
_GATING_SEVERITIES = {"critical", "important"}


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: validate_conformance_review.py <conformance-review.json>",
            file=sys.stderr,
        )
        return 1
    target = Path(sys.argv[1])
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
    # Cross-field consistency (gate-artifact integrity) -- beyond the
    # advisory mirror, because this artifact gates the stage.
    findings = doc.get("findings", [])
    want_has_critical = any(f.get("severity") == "critical" for f in findings)
    if doc.get("has_critical") != want_has_critical:
        print(
            f"conformance-review inconsistent: has_critical={doc.get('has_critical')} "
            f"vs findings-critical={want_has_critical}",
            file=sys.stderr,
        )
        return 1
    want_verdict = (
        "concerns"
        if any(f.get("category") != "unavailable" for f in findings)
        else "ok"
    )
    if doc.get("verdict") != want_verdict:
        print(
            f"conformance-review inconsistent: verdict={doc.get('verdict')!r} "
            f"expected {want_verdict!r} from findings",
            file=sys.stderr,
        )
        return 1
    # Gate verdict: the stage's pass/fail gate, computed here (not by eye). Printed as a
    # one-line JSON the main thread copies (mirrors validate_sim_exit.py's stdout verdict).
    gating = [
        f
        for f in findings
        if f.get("category") in _GATING_CATEGORIES
        and f.get("severity") in _GATING_SEVERITIES
    ]
    flagged = sorted({f.get("tp_id") for f in gating if f.get("tp_id")})
    dominant = (
        Counter(f.get("category") for f in gating).most_common(1)[0][0]
        if gating
        else None
    )
    print(
        json.dumps(
            {
                "gate": "trip" if gating else "clear",
                "flagged": flagged,
                "dominant_category": dominant,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
