#!/usr/bin/env python3
"""Producer self-gate for the (now gating) semantic-review.json artifact.

The rtl-design main thread runs this AFTER aggregating per-child review findings and
BEFORE listing semantic-review.json in artifacts[] / making the gate decision — fix-and-retry
(main-thread re-assembly, not re-dispatch) on a non-zero exit. Validates the file against
references/semantic-review.schema.json (Draft 2020-12), checks verdict<->findings and
has_critical<->severity consistency, then computes the gate verdict (the mechanical
category x severity reduction over the findings, partitioned by fix_locus) and prints it as a
one-line JSON the main thread copies -- so the gate is script-owned, not judged by eye.

Usage: validate_semantic_review.py <semantic-review.json>
Exit: 0 valid (stdout: {"gate","flagged","loci"}) / 1 invalid (stderr message).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "semantic-review.schema.json"
)

# Gate policy: a finding gates (status=fail) iff its category is a gating class AND its
# severity is critical/important. Advisory categories (over-engineering, unavailable) and
# minor severity never gate. This is the schema-bound mechanical reduction over the reviewer's
# findings, partitioned by reviewer-assigned fix_locus -- owned here, not applied by eye.
_GATING_CATEGORIES = {"missing", "wrong-behavior"}
_GATING_SEVERITIES = {"critical", "important"}


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: validate_semantic_review.py <semantic-review.json>", file=sys.stderr
        )
        return 1
    target = Path(sys.argv[1])
    try:
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"semantic-review validate: cannot read {target} or schema: {e}",
            file=sys.stderr,
        )
        return 1
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path)
    )
    if errors:
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(f"semantic-review invalid at {loc}: {err.message}", file=sys.stderr)
        return 1
    # Cross-field consistency (gate-artifact integrity) -- this artifact now gates the stage.
    findings = doc.get("findings", [])
    want_has_critical = any(f.get("severity") == "critical" for f in findings)
    if doc.get("has_critical") != want_has_critical:
        print(
            f"semantic-review inconsistent: has_critical={doc.get('has_critical')} "
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
            f"semantic-review inconsistent: verdict={doc.get('verdict')!r} "
            f"expected {want_verdict!r} from findings",
            file=sys.stderr,
        )
        return 1
    # Gate verdict: the stage's pass/fail gate, computed here (not by eye). Printed as a
    # one-line JSON the main thread copies (mirrors validate_conformance_review.py's stdout).
    gating = [
        f
        for f in findings
        if f.get("category") in _GATING_CATEGORIES
        and f.get("severity") in _GATING_SEVERITIES
    ]
    flagged = [
        {
            "child": f.get("child"),
            "category": f.get("category"),
            "severity": f.get("severity"),
            "fix_locus": f.get("fix_locus"),
        }
        for f in sorted(
            gating, key=lambda f: (f.get("child", ""), f.get("category", ""))
        )
    ]
    loci = {
        "rtl": sorted({f.get("child") for f in gating if f.get("fix_locus") == "rtl"}),
        "spec": sorted(
            {f.get("child") for f in gating if f.get("fix_locus") == "spec"}
        ),
    }
    print(
        json.dumps(
            {"gate": "trip" if gating else "clear", "flagged": flagged, "loci": loci}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
