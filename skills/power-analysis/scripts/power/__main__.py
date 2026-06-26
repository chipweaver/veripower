#!/usr/bin/env python3
"""power — power-analysis-stage CLI.

Verbs (one stage = one tool; see skills/power-analysis/SKILL.md for usage):
  bootstrap   deploy templates + substitute env.sh + render power tests          (exit 0 / 1 / 2)
  finalize    parse PT-PX reports, judge power_mw PPA, assemble result.json       (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
power.* library. Library imports are deferred into each handler (NOT top-level)
so --help and verb dispatch run during incremental per-task TDD, before the
sibling modules (bootstrap.py / result.py) exist. A top-level
`from power import bootstrap, result` would ImportError until both verbs are
built. Keep them lazy. (Library modules themselves use top-level absolute
imports; only this thin dispatcher defers.)
"""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/power-analysis/scripts) on sys.path so absolute
# imports `from power import …` resolve whether this file is run directly
# (python3 …/power/__main__.py) or via `python3 -m power`. abspath() is
# required; the double dirname climbs power/ -> scripts/. NEVER `import result`
# bare inside this package — only `from power import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from power import bootstrap

    return bootstrap.run(a.module, a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from power import result

    return result.finalize(a.workdir, a.module, a.scaffold, a.ppa_targets)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="power", description="power-analysis-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap", help="deploy templates + substitute env.sh + render power tests"
    )
    sp.add_argument("--module", required=True)
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; inferred from Design/rtl-design/filelist.txt when omitted",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "finalize", help="parse PT-PX reports, judge power_mw PPA, assemble result.json"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument(
        "--scaffold",
        required=True,
        help="scaffold-specification.json (power_scenarios[])",
    )
    sp.add_argument(
        "--ppa-targets",
        default="[]",
        dest="ppa_targets",
        help="ppa_targets JSON array (power_mw dim), verbatim from the prompt",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
