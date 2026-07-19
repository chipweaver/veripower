#!/usr/bin/env python3
"""Producer self-gate for the (gating) spec-review.json artifact.

The specification main thread runs this AFTER aggregating the per-child reviewer findings into
spec-review.json and BEFORE the design.md approval gate — fix-and-retry (main-thread re-assembly,
not re-dispatch) on a non-zero exit. Validates against references/spec-review.schema.json (Draft
2020-12), then computes the
gate verdict (the mechanical lens x severity reduction) and prints it as a one-line JSON the main
thread copies -- so the gate is script-owned, not judged by eye.

Gate policy: faithfulness (vs frozen brainstorm intent) AND conformance (vs the §1.4.x pinned
Encoding the child consumes/produces) findings at critical/important BLOCK (gate=trip) -- both have
a reference frame (brainstorm.md / the §1.4.x Encoding row). soundness (micro-arch realizability +
any other observed cross-interface inconsistency, no reference frame) is advisory must-acknowledge
and never blocks; unavailable never blocks. There is no deterministic encoding gate -- encoding
adequacy is a judgment, owned by this LLM lens, not check-coverage.

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
    / "spec-review.schema.json"
)

_GATING_LENSES = {"faithfulness", "conformance"}
_GATING_SEVERITIES = {"critical", "important"}


def gate_verdict(doc: dict) -> dict:
    """Pure lens x severity reduction over doc['findings'] (no schema gate, no I/O).
    The caller guarantees doc is a validated spec-review (main() runs the schema +
    consistency gate first; finalize reads the already-on-disk, already-gated artifact)."""
    findings = doc.get("findings", [])
    gating = [
        f
        for f in findings
        if f.get("lens") in _GATING_LENSES and f.get("severity") in _GATING_SEVERITIES
    ]
    flagged = [
        {"child": f.get("child"), "lens": f.get("lens"), "severity": f.get("severity")}
        for f in sorted(gating, key=lambda f: (f.get("child", ""), f.get("lens", "")))
    ]
    must_ack = [
        {"child": f.get("child"), "severity": f.get("severity")}
        for f in sorted(
            (f for f in findings if f.get("lens") == "soundness"),
            key=lambda f: (f.get("child", ""), f.get("severity", "")),
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
            f"spec-review validate: cannot read {target} or schema: {e}",
            file=sys.stderr,
        )
        return 1
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path)
    )
    if errors:
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(f"spec-review invalid at {loc}: {err.message}", file=sys.stderr)
        return 1
    print(json.dumps(gate_verdict(doc)))
    return 0
