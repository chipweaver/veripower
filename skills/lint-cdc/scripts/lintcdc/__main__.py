#!/usr/bin/env python3
"""lintcdc — lint-cdc-stage CLI.

Verbs (one stage = one tool; see skills/lint-cdc/SKILL.md for usage):
  bootstrap   deploy templates + seed SGDC (carried/cold/template) + sync filelist (exit 0 / 1 / 2)
  finalize    AND the two *-violations.json sidecars, assemble result.json        (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the lintcdc.*
library. Library imports are deferred into each handler because `from lintcdc import …`
only resolves after the sys.path insert below has run. (Library modules themselves use
top-level absolute imports; only this dispatcher defers.)
"""

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


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from lintcdc import bootstrap

    return bootstrap.run(a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from lintcdc import result

    return result.finalize(a.workdir, a.module, a.top, a.fix_owner)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lintcdc", description="lint-cdc-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap",
        help="deploy templates + seed SGDC (carried/cold/template) + sync filelist",
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; read from the specification manifest when omitted",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "finalize",
        help="AND the two *-violations.json sidecars, assemble result.json",
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; defaults to the report header / env.sh $TOP",
    )
    sp.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; the report cannot)",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
