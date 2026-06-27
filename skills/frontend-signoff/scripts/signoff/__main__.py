#!/usr/bin/env python3
"""signoff — frontend-signoff-stage CLI.

Verbs (one stage = one tool; see skills/frontend-signoff/SKILL.md for usage):
  finalize   aggregate the 6 upstream envelopes + evidence into the sign-off verdict;
             write checklist.md + traceability.md + result.json   (exit 0 written / 2 BLOCKED)

Thin dispatcher: the subcommand parses its own flags and calls into the signoff.*
library. The library import is deferred into the handler (NOT top-level) so --help and
verb dispatch run during incremental per-task TDD before the sibling module exists.
(The library module itself uses top-level absolute imports; only this thin dispatcher
defers.)
"""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/frontend-signoff/scripts) on sys.path so absolute imports
# `from signoff import …` resolve whether this file is run directly
# (python3 …/signoff/__main__.py) or via `python3 -m signoff`. abspath() is required;
# the double dirname climbs signoff/ -> scripts/. NEVER `import result` bare inside this
# package — only `from signoff import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_finalize(a: argparse.Namespace) -> int:
    from signoff import result

    return result.finalize(a.workdir, a.module)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="signoff", description="frontend-signoff-stage CLI"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "finalize",
        help="aggregate upstream envelopes + evidence into the sign-off verdict",
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
