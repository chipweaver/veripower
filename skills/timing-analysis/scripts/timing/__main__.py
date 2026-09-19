#!/usr/bin/env python3
"""Prepare tool setup, execute a calculation, or judge existing evidence."""

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


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from timing import bootstrap

    return bootstrap.run(a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    (Path(a.workdir) / "result.json").unlink(missing_ok=True)
    from timing import requirements, result

    return result.finalize(
        a.workdir,
        requirements.mine(requirements.load(a.workdir)),
        requirements.parse_declared(a.requirements),
        a.fix_owner,
        a.fail_reason,
    )


def _cmd_run(a):
    from timing.execute import run

    return run(a.workdir)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="timing", description="timing-analysis-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap",
        help="prepare missing run_sta.tcl and config.tcl from the netlist input",
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; inferred from the single synthesis out/<TOP>_syn.v when omitted",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "run", help="execute the prepared tool script and publish completed outputs"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_run)

    sp = sub.add_parser(
        "finalize", help="parse the PT report, judge setup/hold, assemble result.json"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; the reports cannot)",
    )
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="cause of a run that produced no gradeable report (license, a link_design "
        "or read_sdc abort, a crash after reporting); supplying it declares the failure "
        "and wins over the gate.",
    )
    sp.add_argument(
        "--requirements",
        default=None,
        help="your verdict on timing-analysis rows without a numeric target, as a JSON "
        'array of {"id", "met", "measured", "actual"}; timing_slack_ns targets are computed',
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(
            f"[timing {args.cmd}] BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
