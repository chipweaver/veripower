#!/usr/bin/env python3
"""spec — specification-stage CLI.

Verbs (one stage = one tool):
  check-ledger        validate requirements.json; print the ledger and boundary gate view (stdout: JSON)
  check-crossrefs     hint↔requirement join + phantom clock domain (stdout: verdict JSON; exit 0/1, 2 BLOCKED)
  derive-constraints  generate SDC/SGDC from clocks.json + top-io.json (stdout: JSON; fail-loud)
  finalize            assemble the lean result.json         (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
spec.* library. Library imports are deferred into each handler, not top-level,
so `--help` and verb dispatch keep working before every sibling library exists —
which is what makes this file copyable as a per-stage template. Keep them lazy.
(Library modules themselves import at top level; only this dispatcher defers.)
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Put the package PARENT (…/specification/scripts) on sys.path so absolute
# imports `from spec import …` resolve whether this file is run directly
# (python3 …/spec/__main__.py) or via `python3 -m spec`. abspath() is required;
# the double dirname climbs spec/ -> scripts/. Always `from spec import <mod>`,
# never a bare `import <mod>`: a bare name binds the top-level slot and collides
# with the same module name in another stage's package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_check_ledger(a: argparse.Namespace) -> int:
    from spec import ledger

    return ledger.run(a.workdir)


def _cmd_check_crossrefs(a: argparse.Namespace) -> int:
    from spec import crossrefs

    return crossrefs.run(a.workdir)


def _cmd_derive_constraints(a: argparse.Namespace) -> int:
    from spec import constraints

    print(
        json.dumps(
            constraints.derive_constraints(a.workdir), ensure_ascii=False, indent=2
        )
    )
    return 0


def _cmd_finalize(a: argparse.Namespace) -> int:
    from spec import result

    return result.finalize(a.workdir, fail_reason=a.fail_reason)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spec", description="specification-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "check-ledger",
        help="validate requirements.json and print what the ledger and boundary gate hands the human",
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_check_ledger)

    sp = sub.add_parser(
        "check-crossrefs", help="hint↔requirement join + phantom clock domain"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_check_crossrefs)

    sp = sub.add_parser("derive-constraints", help="generate SDC/SGDC (fail-loud)")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_derive_constraints)

    sp = sub.add_parser("finalize", help="assemble the lean result.json")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="the one-line reason this round could not deliver; its presence is the failure. "
        "Absent = the stage delivered what it owes",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from spec.sidecar import SidecarError

    try:
        return args.func(args)
    except SidecarError as exc:
        # One failure protocol for every verb. A sidecar defect is the caller's to fix, so it
        # reaches them as the message the reader is told to act on — not as a traceback, which
        # is the one thing the skills tell an agent never to read.
        print(f"[spec {args.cmd}] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
