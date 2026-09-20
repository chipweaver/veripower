#!/usr/bin/env python3
"""Command-line operations for the sim stage."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/simulation/scripts) on sys.path so absolute imports
# `from sim import …` resolve whether this file is run directly
# (python3 …/sim/__main__.py) or via `python3 -m sim`. abspath() is required;
# the double dirname climbs sim/ -> scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sim", description="simulation-stage CLI")
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "bootstrap", help="deploy infra + optional scaffold into a run workdir"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="the simulation-plan workdir (renders the UVM scaffold when given)",
    )

    command_parser = subcommands.add_parser(
        "check-materialization",
        help="presence gate over the materialized TB (env-exit self-gate)",
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument("--plan", required=True, type=Path)

    command_parser = subcommands.add_parser(
        "finalize", help="write result.json (--phase fail | final)"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--phase",
        required=True,
        choices=["fail", "final"],
        help="`fail` closes the round on a failure the caller already holds a reason for; "
        "`final` checks materialization, review, coverage and case results on disk.",
    )
    command_parser.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="the simulation-plan workdir (required for --phase final)",
    )
    command_parser.add_argument(
        "--requirements",
        type=Path,
        default=None,
        help="the specification requirements.json; its coverage bounds judged by simulation "
        "are the coverage gate (required for --phase final)",
    )
    command_parser.add_argument("--check-review", type=Path, default=None)
    command_parser.add_argument(
        "--fail-reason",
        default=None,
        help="unresolved violation or incomplete work, even if tool results otherwise pass",
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
        if args.cmd == "bootstrap":
            from sim import bootstrap

            return bootstrap.run(args.workdir, scaffold=args.plan)
        elif args.cmd == "check-materialization":
            from sim import materialization

            return materialization.run(args.workdir, args.plan)
        else:
            from sim import result

            (Path(args.workdir) / "result.json").unlink(missing_ok=True)
            if args.phase == "final" and (
                not (args.plan and args.requirements and args.check_review)
            ):
                print(
                    "[sim finalize] ERROR: --plan, --requirements and --check-review are required for --phase final",
                    file=sys.stderr,
                )
                return 2
            if args.phase == "fail" and (
                not (args.fail_reason and args.fail_reason.strip())
            ):
                print(
                    "[sim finalize] ERROR: --fail-reason is required for --phase fail",
                    file=sys.stderr,
                )
                return 2
            return result.finalize(
                args.workdir,
                phase=args.phase,
                scaffold=args.plan,
                requirements=args.requirements,
                check_review=args.check_review,
                fail_reason=args.fail_reason,
                fix_owner=args.fix_owner,
            )
    except (OSError, ValueError) as error:
        print(f"[sim {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
