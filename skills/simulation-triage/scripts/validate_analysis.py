#!/usr/bin/env python3
"""Producer self-gate for the simulation-triage ANALYSIS.

Validates a JSON payload (piped on stdin) against analysis.schema.json.
Exit 0 = valid; exit 1 = invalid (formatted error on stderr). Writes no
files — consistent with simulation-triage's read-only Iron Rule. The skill
runs this before emitting the ANALYSIS block and fixes-and-reruns on failure
(mirrors simulation-plan/scripts/validate_scaffold.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> None:
    ap = argparse.ArgumentParser(prog="validate_analysis.py")
    ap.add_argument("--schema", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--json-file")
    g.add_argument("--json-stdin", action="store_true")
    args = ap.parse_args()

    if args.json_stdin:
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.json_file).read_text()
        except OSError as e:
            print(f"--json-file read error: {e}", file=sys.stderr)
            sys.exit(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"ANALYSIS is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        schema = json.loads(Path(args.schema).read_text())
        errors = sorted(
            Draft202012Validator(schema).iter_errors(payload),
            key=lambda e: list(e.absolute_path),
        )
    except Exception as e:  # malformed schema / library failure
        print(f"validation internal error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    if errors:
        for e in errors:
            loc = "/".join(str(p) for p in e.absolute_path) or "(root)"
            print(f"schema violation at {loc}: {e.message}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
