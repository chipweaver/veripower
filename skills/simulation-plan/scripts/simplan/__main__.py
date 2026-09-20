#!/usr/bin/env python3
"""simplan — simulation-plan-stage CLI.

Verbs (one stage = one tool):
  check-scaffold        structural+semantic+coverage gate        (exit 0 OK / 1 fix-message)
  finalize              assemble the lean result.json            (exit 0 written / 2 BLOCKED)

Each handler loads its implementation after argument parsing.
"""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/simulation-plan/scripts) on sys.path so absolute imports
# `from simplan import …` resolve whether this file is run directly
# (python3 …/simplan/__main__.py) or via `python3 -m simplan`. abspath() is required;
# the double dirname climbs simplan/ -> scripts/. NEVER `import _md` bare inside this
# package — only `from simplan import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_check_scaffold(a: argparse.Namespace) -> int:
    from simplan import scaffold

    return scaffold.run(a.plan, a.spec)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from simplan import result

    return result.finalize(
        a.workdir,
        a.spec,
        fail_reason=a.fail_reason,
        fix_owner=a.fix_owner,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="simplan", description="simulation-plan-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("check-scaffold", help="structural + semantic + coverage gate")
    sp.add_argument(
        "--plan",
        required=True,
        type=Path,
        help="the simulation-plan workdir holding the sidecars",
    )
    sp.add_argument(
        "--spec",
        required=True,
        type=Path,
        help="the specification workdir: check-hints.json and requirements.json are read from it",
    )
    sp.set_defaults(func=_cmd_check_scaffold)

    sp = sub.add_parser("finalize", help="assemble the lean result.json")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--spec",
        required=True,
        type=Path,
        help="the specification workdir: the pass path re-runs check-scaffold against it",
    )
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="the one-line reason this round could not deliver; its presence is the failure. "
        "Absent = the stage delivered what it owes",
    )
    sp.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; no gate can derive it)",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
