#!/usr/bin/env python3
"""rtl validate-review — producer self-gate for the gating semantic-review.json artifact.

Validates the file against references/semantic-review.schema.json (Draft 2020-12), then computes
the gate verdict (the mechanical category x severity reduction over the findings, partitioned by
fix_locus) and prints it as a one-line JSON the main thread routes on -- so the gate is
script-owned, not judged by eye. Nothing is copied: the finalize verb re-runs the same
load_validated + compute_gate in-process (rtl.result) and writes the verdict itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "semantic-review.schema.json"
)

# Gate policy: a finding gates (status=fail) iff its category is a gating class AND its
# severity is critical/important. Advisory categories (over-engineering, unavailable) and
# minor severity never gate. This is the schema-bound mechanical reduction over the reviewer's
# findings, partitioned by reviewer-assigned fix_locus -- owned here, not applied by eye.
_GATING_CATEGORIES = {"missing", "wrong-behavior"}
_GATING_SEVERITIES = {"critical", "important"}

# confidence ordering for the spec_confidence reduction below (low < medium < high). rtl-design
# has no triage, so this self-reported confidence is the only upstream-route trust signal the
# kernel gets on a spec-locus trip -- missing confidence defaults to the conservative "low".
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def compute_gate(doc: dict) -> dict:
    """Pure gate reduction over an already-valid semantic-review doc: the mechanical
    category x severity filter partitioned by fix_locus. No schema checks here -- both callers
    (validate, and finalize via load_validated) validate before reducing."""
    findings = doc.get("findings", [])
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
    # spec_confidence: the MINIMUM confidence over every spec-locus finding (not just the
    # gating subset above) -- conservative, since any low-confidence spec attribution anywhere
    # should pull down trust in the "this is truly spec-rooted" call the downstream route makes.
    spec_findings = [
        f
        for f in findings
        if f.get("fix_locus") == "spec" and f.get("category") != "unavailable"
    ]
    spec_confidence = (
        min(
            (f.get("confidence", "low") for f in spec_findings),
            key=lambda c: _CONFIDENCE_RANK[c],
        )
        if spec_findings
        else None
    )
    return {
        "gate": "trip" if gating else "clear",
        "flagged": flagged,
        "loci": loci,
        "spec_confidence": spec_confidence,
    }


class ReviewError(Exception):
    """semantic-review.json is unreadable or schema-invalid: no gate may be reduced from it."""


def schema_errors(doc: dict) -> list:
    """Every schema violation in `doc`, one message per error, outermost path first."""
    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    return [
        f"semantic-review invalid at {'/'.join(str(p) for p in err.path) or '<root>'}: "
        f"{err.message}"
        for err in sorted(
            Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path)
        )
    ]


def load_validated(review_path) -> dict:
    """Read + schema-validate semantic-review.json, or raise ReviewError.

    The deterministic backstop the finalize verb reduces the gate over. compute_gate reads
    `findings` through .get() defaults, so an empty or malformed doc would otherwise fold in as
    gate=clear; nothing forces the skill to have run the validate-review verb first, and the
    kernel schema-validates only result.json at reap. This is the sole check standing between a
    hand-written oracle artifact and status=pass.
    """
    target = Path(review_path)
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ReviewError(f"cannot read {target}: {e}") from e
    errors = schema_errors(doc)
    if errors:
        raise ReviewError("; ".join(errors))
    return doc


def validate(review_path) -> int:
    target = Path(review_path)
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
        errors = schema_errors(doc)
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"semantic-review validate: cannot read {target} or schema: {e}",
            file=sys.stderr,
        )
        return 1
    if errors:
        for msg in errors:
            print(msg, file=sys.stderr)
        return 1
    print(json.dumps(compute_gate(doc)))
    return 0
