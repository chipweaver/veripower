#!/usr/bin/env python3
"""timing — timing-analysis-stage CLI.

Verbs (one stage = one tool; see skills/timing-analysis/SKILL.md for usage):
  bootstrap   deploy run_sta.tcl/config.tcl into the run workdir + substitute   (exit 0 / 1 / 2)
  finalize    parse the PT STA report, judge setup/hold, assemble result.json   (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
timing.* library. Library imports are deferred into each handler (NOT top-level)
so --help and verb dispatch run during incremental per-task TDD, before the
sibling modules (bootstrap.py / result.py) exist. A top-level
`from timing import bootstrap, result` would ImportError until both verbs are
built. Keep them lazy. (Library modules themselves use top-level absolute
imports; only this thin dispatcher defers.)
"""

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
    from timing import result

    # --top is optional for timing finalize; default to --module (design §5.0).
    return result.finalize(a.workdir, a.module, a.top or a.module, a.fix_owner)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="timing", description="timing-analysis-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap", help="deploy run_sta.tcl/config.tcl + substitute into the workdir"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; inferred from the single synthesis out/<TOP>_syn.v when omitted",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "finalize", help="parse the PT report, judge setup/hold, assemble result.json"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument(
        "--top", default=None, help="top module; defaults to --module when omitted"
    )
    sp.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; the reports cannot)",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
