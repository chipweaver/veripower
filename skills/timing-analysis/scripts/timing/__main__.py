#!/usr/bin/env python3
"""Command-line operations for the timing stage."""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/timing-analysis/scripts) on sys.path so absolute
# imports `from timing import …` resolve whether this file is run directly
# (python3 …/timing/__main__.py) or via `python3 -m timing`. abspath() is
# required; the double dirname climbs timing/ -> scripts/. NEVER `import result`
# bare inside this package — only `from timing import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timing", description="timing-analysis-stage CLI"
    )
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "bootstrap",
        help="prepare missing run_sta.tcl and config.tcl from the netlist input",
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--top",
        default=None,
        help="top module; inferred from the single synthesis out/<TOP>_syn.v when omitted",
    )

    command_parser = subcommands.add_parser(
        "run", help="execute the prepared tool script and publish completed outputs"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)

    command_parser = subcommands.add_parser(
        "finalize", help="parse the PT report, judge setup/hold, assemble result.json"
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
        help="cause of a run that produced no gradeable report (license, a link_design "
        "or read_sdc abort, a crash after reporting); supplying it declares the failure "
        "and wins over the gate.",
    )
    command_parser.add_argument(
        "--requirements",
        default=None,
        help="your verdict on timing-analysis rows without a numeric target, as a JSON "
        'array of {"id", "met", "measured", "actual"}; timing_slack_ns targets are computed',
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "bootstrap":
            from timing import bootstrap

            return bootstrap.run(args.workdir, top=args.top)
        elif args.cmd == "finalize":
            (Path(args.workdir) / "result.json").unlink(missing_ok=True)
            from timing import requirements, result

            return result.finalize(
                args.workdir,
                requirements.load_requirements(args.workdir),
                requirements.parse_declared(args.requirements),
                args.fix_owner,
                args.fail_reason,
            )
        else:
            from timing.execute import run

            return run(args.workdir)
    except (OSError, ValueError) as error:
        print(f"[timing {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
