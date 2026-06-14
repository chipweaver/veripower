#!/usr/bin/env python3
"""Producer self-gate for the conformance-review.json artifact (U6 gate).

The simulation main thread runs this AFTER assembling the reviewer's findings into
conformance-review.json and BEFORE listing it in artifacts[] / making the gate
decision — fix-and-retry (main-thread re-assembly, not re-dispatch) on a non-zero exit.
Validates the file against references/conformance-review.schema.json (Draft 2020-12),
then checks verdict<->findings and has_critical<->severity consistency (spec 4.6) --
beyond the advisory semantic-review mirror, because this artifact gates the stage.

Usage: validate_conformance_review.py <conformance-review.json>
Exit: 0 valid / 1 invalid (stderr message).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "conformance-review.schema.json"
)


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
    # Cross-field consistency (gate-artifact integrity; spec 4.6) -- beyond the
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
