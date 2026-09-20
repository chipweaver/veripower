#!/usr/bin/env python3
"""Command-line operations for the power stage."""

import argparse
import json
import os
import sys
from pathlib import Path

# Put the package PARENT (…/power-analysis/scripts) on sys.path so absolute
# imports `from power import …` resolve whether this file is run directly
# (python3 …/power/__main__.py) or via `python3 -m power`. abspath() is
# required; the double dirname climbs power/ -> scripts/. NEVER `import result`
# bare inside this package — only `from power import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="power", description="power-analysis-stage CLI"
    )
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "bootstrap", help="prepare editable setup; execution checks its own inputs"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--top",
        default=None,
        help="top module; inferred from the injected synthesis netlist's out/<TOP>_syn.v when omitted",
    )

    for mode in ("compile", "simulate", "calculate"):
        command_parser = subcommands.add_parser(mode)
        command_parser.add_argument("--workdir", required=True, type=Path)

    command_parser = subcommands.add_parser(
        "finalize", help="parse PT-PX reports, judge power_mw PPA, assemble result.json"
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
        help="unresolved reason the measurement is invalid or incomplete, even if reports "
        "contain numbers; declares failure without qualifying those measurements",
    )
    command_parser.add_argument(
        "--requirements",
        default=None,
        help="judgments for power-analysis rows without numeric targets: JSON array entries "
        "require id, met and measured; actual is optional. Numeric targets are computed",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "bootstrap":
            from power import bootstrap

            return bootstrap.run(args.workdir, top=args.top)
        elif args.cmd == "finalize":
            inputs = json.loads((Path(args.workdir) / "dispatch.json").read_text())[
                "inputs"
            ]
            (Path(args.workdir) / "result.json").unlink(missing_ok=True)
            from power import requirements, result

            return result.finalize(
                args.workdir,
                inputs["plan"],
                requirements.load_requirements(args.workdir),
                requirements.parse_declared(args.requirements),
                args.fix_owner,
                args.fail_reason,
            )
        else:
            from power.execute import run

            return run(args.workdir, args.cmd)
    except (OSError, ValueError) as error:
        print(f"[power {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
