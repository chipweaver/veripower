#!/usr/bin/env python3
"""rtl — rtl-design-stage CLI.

One verb (see skills/rtl-design/SKILL.md for usage):
  finalize          write the lean result.json envelope                 (exit 0 written / 2 BLOCKED)

Thin dispatcher: the subcommand parses its own flags and calls into the rtl.*
library. Library imports are deferred into the handler (NOT top-level) so --help
and verb dispatch keep working when a sibling module is absent or unimportable —
a top-level `from rtl import result` would take the whole CLI down with it.
(Library modules themselves use top-level absolute imports; only this thin
dispatcher defers.)
"""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/rtl-design/scripts) on sys.path so absolute imports
# `from rtl import …` resolve whether this file is run directly
# (python3 …/rtl/__main__.py) or via `python3 -m rtl`. abspath() is required;
# the double dirname climbs rtl/ -> scripts/. NEVER `import _ledger` bare inside
# this package — only `from rtl import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_finalize(a: argparse.Namespace) -> int:
    from rtl import result

    return result.finalize(
        a.workdir, a.module, a.top, a.manifest, a.fail_reason, a.fix_owner
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rtl", description="rtl-design-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("finalize", help="write the lean result.json envelope")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument("--top", required=True, help="top module (= manifest.module)")
    sp.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Design/specification/manifest.json",
    )
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="one-line reason for an early exit no on-disk state can express (a child that "
        "reported BLOCKED, or a malformed sidecar); writes the status=fail envelope directly",
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
