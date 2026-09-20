#!/usr/bin/env python3
"""Command-line operations for the lintcdc stage."""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/lint-cdc/scripts) on sys.path so absolute imports
# `from lintcdc import …` resolve whether this file is run directly
# (python3 …/lintcdc/__main__.py) or via `python3 -m lintcdc`. abspath() is
# required; the double dirname climbs lintcdc/ -> scripts/. NEVER `import result`
# bare inside this package — only `from lintcdc import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lintcdc", description="lint-cdc-stage CLI")
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "bootstrap",
        help="deploy templates + seed SGDC (carried/cold/template) + sync filelist",
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--top",
        default=None,
        help="top module; read from the specification manifest when omitted",
    )

    command_parser = subcommands.add_parser(
        "finalize",
        help="AND the two *-violations.json sidecars, assemble result.json",
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; the report cannot)",
    )
    command_parser.add_argument(
        "--fail-reason",
        default=None,
        help="force status=fail with this reason; use it when `make` died before the "
        "parser wrote its sidecar, so the reason on its stderr is the precise one",
    )
    command_parser.add_argument(
        "--requirements",
        default=None,
        help="your verdict on each requirements.json row judged by lint-cdc, as a JSON array "
        'of {"id", "met", "actual"}',
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "bootstrap":
            from lintcdc import bootstrap

            return bootstrap.run(args.workdir, top=args.top)
        else:
            (Path(args.workdir) / "result.json").unlink(missing_ok=True)
            from lintcdc import requirements, result

            return result.finalize(
                args.workdir,
                requirements.load_requirements(args.workdir),
                requirements.parse_declared(args.requirements),
                args.fix_owner,
                args.fail_reason,
            )
    except (OSError, ValueError) as error:
        print(f"[lintcdc {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
