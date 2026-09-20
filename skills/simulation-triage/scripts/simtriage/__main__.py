#!/usr/bin/env python3
"""Command-line operations for the simtriage stage."""

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simtriage", description="simulation-triage-stage CLI"
    )
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "finalize", help="schema-gate the analysis judgment, then write result.json"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    g = command_parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--json-file", type=Path)
    g.add_argument("--json-stdin", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from simtriage import result

        return result.finalize(args.workdir, args.json_file, args.json_stdin)
    except (OSError, ValueError) as error:
        print(f"[simtriage {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
