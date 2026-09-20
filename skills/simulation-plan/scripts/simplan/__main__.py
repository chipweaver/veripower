#!/usr/bin/env python3
"""Command-line operations for the simplan stage."""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/simulation-plan/scripts) on sys.path so absolute imports
# `from simplan import …` resolve whether this file is run directly
# Support both direct script execution and python3 -m simplan.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simplan", description="simulation-plan-stage CLI"
    )
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "check-scaffold", help="structural + semantic + coverage gate"
    )
    command_parser.add_argument(
        "--plan",
        required=True,
        type=Path,
        help="the simulation-plan workdir holding the sidecars",
    )
    command_parser.add_argument(
        "--spec",
        required=True,
        type=Path,
        help="the specification workdir: check-hints.json and requirements.json are read from it",
    )

    command_parser = subcommands.add_parser(
        "finalize", help="assemble the lean result.json"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--spec",
        required=True,
        type=Path,
        help="the specification workdir: the pass path re-runs check-scaffold against it",
    )
    command_parser.add_argument(
        "--fail-reason",
        default=None,
        help="the one-line reason this round could not deliver; its presence is the failure. "
        "Absent = the stage delivered what it owes",
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
        if args.cmd == "check-scaffold":
            from simplan import scaffold

            return scaffold.run(args.plan, args.spec)
        else:
            from simplan import result

            return result.finalize(
                args.workdir,
                args.spec,
                fail_reason=args.fail_reason,
                fix_owner=args.fix_owner,
            )
    except (OSError, ValueError) as error:
        print(f"[simplan {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
