#!/usr/bin/env python3
"""Producer self-gate for the advisory semantic-review.json artifact.

The rtl-design main thread runs this AFTER aggregating per-child review findings and
BEFORE listing semantic-review.json in artifacts[] — fix-and-retry on a non-zero exit.
Validates the file against references/semantic-review.schema.json (Draft 2020-12).

Usage: validate_semantic_review.py <semantic-review.json>
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
    / "semantic-review.schema.json"
)


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
