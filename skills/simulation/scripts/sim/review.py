#!/usr/bin/env python3
"""sim validate-review — producer self-gate for the gating conformance-review.json artifact.

Validates the file against references/conformance-review.schema.json (Draft 2020-12), checks
verdict<->findings and has_critical<->severity consistency, then computes the gate verdict (the
mechanical category x severity reduction over the findings) and prints it as a one-line JSON the
main thread copies — so the gate is script-owned, not judged by eye. `compute_gate` is reused
in-process by the finalize verb (sim.result).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "conformance-review.schema.json"
)

# Gate policy: a finding gates (status=fail) iff its category is a gating class AND its severity is
# critical/important. Advisory categories (unverifiable-arch, unavailable) and minor never gate.
_GATING_CATEGORIES = {"missing", "wrong-behavior", "fake-green", "intent-defect"}
_GATING_SEVERITIES = {"critical", "important"}


def compute_gate(doc: dict) -> dict:
    """Pure category x severity reduction over findings -> the stage gate verdict. No schema/
    consistency checks here (validate() does those first; finalize calls this over the on-disk doc)."""
    findings = doc.get("findings", [])
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
    return {
        "gate": "trip" if gating else "clear",
        "flagged": flagged,
        "dominant_category": dominant,
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
    print(json.dumps(compute_gate(doc)))
    return 0
