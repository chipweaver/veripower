#!/usr/bin/env python3
"""power — power-analysis-stage CLI.

Verbs (one stage = one tool):
  bootstrap   deploy templates + substitute env.sh + render power tests          (exit 0 / 1 / 2)
  finalize    parse PT-PX reports, judge the power requirements, assemble result.json (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
power.* library. Library imports are deferred into each handler (NOT top-level)
so --help and verb dispatch run during incremental per-task TDD, before the
sibling modules (bootstrap.py / result.py) exist. A top-level
`from power import bootstrap, result` would ImportError until both verbs are
built. Keep them lazy. (Library modules themselves use top-level absolute
imports; only this thin dispatcher defers.)
"""

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


def _inputs(workdir) -> dict:
    """The injected `inputs` table from `<workdir>/dispatch.json`. Every upstream
    location this stage reads is in here, so none of them is a path the caller types."""
    return json.loads((Path(workdir) / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from power import bootstrap

    return bootstrap.run(a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from power import requirements, result

    return result.finalize(
        a.workdir,
        _inputs(a.workdir)["scaffold"],
        requirements.mine(requirements.load(a.workdir)),
        requirements.parse_declared(a.requirements),
        a.fix_owner,
        a.fail_reason,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="power", description="power-analysis-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap", help="deploy templates + substitute env.sh + render power tests"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; inferred from the injected synthesis netlist's out/<TOP>_syn.v when omitted",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "finalize", help="parse PT-PX reports, judge power_mw PPA, assemble result.json"
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
        help="cause of a run with no gradeable reports (missing external reference, "
        "license, a non-zero make); supplying it declares the failure and skips the "
        "gate.",
    )
    sp.add_argument(
        "--requirements",
        default=None,
        help="your verdict on each requirements.json row judged by power-analysis that carries "
        'no target, as a JSON array of {"id", "met", "actual"}; rows with a target are compared here',
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
