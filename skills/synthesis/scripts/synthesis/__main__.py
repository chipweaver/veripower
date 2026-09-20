#!/usr/bin/env python3
"""Command-line operations for the synthesis stage."""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/synthesis/scripts) on sys.path so absolute imports
# `from synthesis import …` resolve whether this file is run directly
# (python3 …/synthesis/__main__.py) or via `python3 -m synthesis`. abspath() is
# required; the double dirname climbs synthesis/ -> scripts/. NEVER `import result`
# bare inside this package — only `from synthesis import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthesis", description="synthesis-stage CLI"
    )
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "bootstrap",
        help="deploy templates + render RTL loading and tool configuration into the workdir",
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--top",
        default=None,
        help="top module; read from the specification manifest when omitted",
    )

    command_parser = subcommands.add_parser(
        "run", help="execute the prepared tool script and publish completed outputs"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)

    command_parser = subcommands.add_parser(
        "finalize", help="parse DC reports, judge PPA, assemble result.json"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; the reports cannot)",
    )
    command_parser.add_argument(
        "--fail-reason",
        default=None,
        help="cause of a run with no gradeable reports (license, elaborate/compile "
        "abort, crash after reporting); supplying it declares the failure and wins "
        "over the gate.",
    )
    command_parser.add_argument(
        "--requirements",
        default=None,
        help="your verdict on each requirements.json row judged by synthesis that carries no "
        'target, as a JSON array of {"id", "met", "actual"}; rows with a target are compared here',
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "bootstrap":
            from synthesis import bootstrap

            return bootstrap.run(args.workdir, top=args.top)
        elif args.cmd == "finalize":
            (Path(args.workdir) / "result.json").unlink(missing_ok=True)
            from synthesis import requirements, result

            return result.finalize(
                args.workdir,
                requirements.load_requirements(args.workdir),
                requirements.parse_declared(args.requirements),
                args.fix_owner,
                args.fail_reason,
            )
        else:
            from synthesis.execute import run

            return run(args.workdir)
    except (OSError, ValueError) as error:
        print(f"[synthesis {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
