#!/usr/bin/env python3
"""simtriage — simulation-triage-stage CLI.

Verbs (one stage = one tool; see skills/simulation-triage/SKILL.md for usage):
  validate-analysis   schema-gate the analysis.json routing block   (exit 0 valid / 1 invalid; writes no files)

simulation-triage is an N=1 producer self-gate: it writes no result.json and has no
finalize / --workdir (canonical read-only + scratch-writable Iron Rule — the skill lands
analysis.json itself, directly to disk under its own Verification/simulation-triage/**,
not through this script). Thin dispatcher: the subcommand parses its
own flags and calls into the simtriage.* library. The library import is deferred into
the handler (NOT top-level) so --help and verb dispatch run during incremental per-task
TDD before the sibling module exists. (The library module itself uses top-level absolute
imports; only this thin dispatcher defers.)
"""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/simulation-triage/scripts) on sys.path so absolute imports
# `from simtriage import …` resolve whether this file is run directly
# (python3 …/simtriage/__main__.py) or via `python3 -m simtriage`. abspath() is required;
# the double dirname climbs simtriage/ -> scripts/. NEVER `import analysis` bare inside
# this package — only `from simtriage import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_validate_analysis(a: argparse.Namespace) -> int:
    from simtriage import analysis

    return analysis.validate(a.json_file, a.json_stdin, a.schema)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="simtriage", description="simulation-triage-stage CLI"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "validate-analysis", help="schema-gate the ANALYSIS routing block"
    )
    sp.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="optional schema override (default: sibling references/analysis.schema.json)",
    )
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--json-file", type=Path)
    g.add_argument("--json-stdin", action="store_true")
    sp.set_defaults(func=_cmd_validate_analysis)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
