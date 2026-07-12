#!/usr/bin/env python3
"""simtriage — simulation-triage-stage CLI.

Verbs (one stage = one tool; see skills/simulation-triage/SKILL.md for usage):
  finalize   schema-gate the analysis judgment, then atomically write result.json
             (exit 0 written / 1 schema violation / 2 BLOCKED)

Task C7: simulation-triage is now an ordinary kernel-scheduled rule (rules.py:
proof=None) — its result.json lands under its own kernel-issued {workdir}
(Verification/simulation-triage/runs/<N>/), written by this CLI's `finalize` verb
(the old runs/<sim_run>/analysis.json + top-level pointer double-file mechanism is
retired). Thin dispatcher: the subcommand parses its own flags and calls into the
simtriage.* library. The library import is deferred into the handler (NOT top-level)
so --help and verb dispatch run during incremental per-task TDD before the sibling
module exists. (The library module itself uses top-level absolute imports; only this
thin dispatcher defers.)
"""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/simulation-triage/scripts) on sys.path so absolute imports
# `from simtriage import …` resolve whether this file is run directly
# (python3 …/simtriage/__main__.py) or via `python3 -m simtriage`. abspath() is required;
# the double dirname climbs simtriage/ -> scripts/. NEVER `import result` bare inside
# this package — only `from simtriage import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_finalize(a: argparse.Namespace) -> int:
    from simtriage import result

    return result.finalize(a.workdir, a.module, a.json_file, a.json_stdin, a.schema)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="simtriage", description="simulation-triage-stage CLI"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "finalize", help="schema-gate the analysis judgment, then write result.json"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="optional stage_specific schema override (default: the subschema folded "
        "into the sibling references/result.schema.json)",
    )
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--json-file", type=Path)
    g.add_argument("--json-stdin", action="store_true")
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
