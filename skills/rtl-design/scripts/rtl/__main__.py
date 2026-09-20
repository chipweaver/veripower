#!/usr/bin/env python3
"""Command-line operations for the rtl stage."""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/rtl-design/scripts) on sys.path so absolute imports
# `from rtl import …` resolve whether this file is run directly
# (python3 …/rtl/__main__.py) or via `python3 -m rtl`. abspath() is required;
# the double dirname climbs rtl/ -> scripts/. NEVER `import ledger` bare inside
# this package — only `from rtl import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rtl", description="rtl-design-stage CLI")
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "finalize", help="write the lean result.json envelope"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--fail-reason",
        default=None,
        help="unresolved requirement violation or incomplete work, even if compilation and "
        "file checks pass; writes the failure result",
    )
    command_parser.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; no gate can derive it)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        from rtl import result

        return result.finalize(args.workdir, args.fail_reason, args.fix_owner)
    except (OSError, ValueError) as error:
        print(f"[rtl {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
