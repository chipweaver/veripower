#!/usr/bin/env python3
"""rtl — rtl-design-stage CLI.

Verbs (one stage = one tool; see skills/rtl-design/SKILL.md for usage):
  seed              carry prior canonical RTL products fwd (whitelist)  (stdout: JSON; exit 0)
  check-partition   pre-dispatch coverage+purity gate (manifest+top)    (stdout: verdict; exit 0/1)
  assemble          build ledger/filelist/README + post exit-gate       (stdout: verdict; exit 0/1)
  check-conformance spec<->RTL presence gate                            (stdout: verdict; exit 0/1)
  validate-review   semantic-review.json schema + gate                  (stdout: gate JSON; exit 0/1)
  classify-delta    freeze-branch selector                              (stdout: verdict JSON; exit 0/1)
  finalize          assemble the lean result.json                       (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the rtl.*
library. Library imports are deferred into each handler (NOT top-level) so --help
and verb dispatch run during incremental per-task TDD, before the sibling modules
exist. A top-level `from rtl import seed, partition, …` would ImportError until
every verb is built. Keep them lazy. (Library modules themselves use top-level
absolute imports; only this thin dispatcher defers.)
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


def _cmd_seed(a: argparse.Namespace) -> int:
    from rtl import seed

    return seed.run(a.workdir, a.canonical, freeze=a.freeze)


def _cmd_classify_delta(a: argparse.Namespace) -> int:
    from rtl import classify

    return classify.run(a.canonical_result, a.spec_dir)


def _cmd_check_partition(a: argparse.Namespace) -> int:
    from rtl import partition

    return partition.run(a.manifest, a.top)


def _cmd_assemble(a: argparse.Namespace) -> int:
    from rtl import assemble

    return assemble.run(a.workdir, a.manifest, a.top, seeded=a.seeded)


def _cmd_check_conformance(a: argparse.Namespace) -> int:
    from rtl import conformance

    return conformance.run(a.workdir, a.manifest, a.top, a.ledger, a.design)


def _cmd_validate_review(a: argparse.Namespace) -> int:
    from rtl import review

    return review.validate(a.review)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from rtl import result

    return result.finalize(a.workdir, a.module, a.top, a.manifest)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rtl", description="rtl-design-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "seed",
        help="carry prior canonical RTL products forward (whitelist, no-clobber; "
        "never result.json)",
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--canonical",
        type=Path,
        default=None,
        help="prior canonical dir; default = {workdir}/../..",
    )
    sp.add_argument(
        "--freeze",
        action="store_true",
        help="freeze branch only: additionally byte-carry semantic-review.json (keeps its pin alive)",
    )
    sp.set_defaults(func=_cmd_seed)

    sp = sub.add_parser(
        "check-partition", help="pre-dispatch coverage+purity gate (manifest+top)"
    )
    sp.add_argument("--manifest", required=True, type=Path)
    sp.add_argument("--top", required=True)
    sp.set_defaults(func=_cmd_check_partition)

    sp = sub.add_parser(
        "assemble", help="build ledger/filelist/README + post exit-gate"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--manifest", required=True, type=Path)
    sp.add_argument("--top", required=True)
    sp.add_argument(
        "--seeded",
        action="store_true",
        help="overlay onto the existing {workdir}/.child_reports.json (incremental/rework + the 4.3 loop)",
    )
    sp.set_defaults(func=_cmd_assemble)

    sp = sub.add_parser("check-conformance", help="spec<->RTL presence gate")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--manifest", required=True, type=Path)
    sp.add_argument("--top", required=True)
    sp.add_argument("--ledger", required=True, type=Path)
    sp.add_argument("--design", required=True, type=Path)
    sp.set_defaults(func=_cmd_check_conformance)

    sp = sub.add_parser("validate-review", help="semantic-review.json schema + gate")
    sp.add_argument("--review", required=True, type=Path)
    sp.set_defaults(func=_cmd_validate_review)

    sp = sub.add_parser(
        "classify-delta", help="freeze-branch selector: first-run|freeze|proceed"
    )
    sp.add_argument("--spec-dir", required=True, type=Path, help="Design/specification")
    sp.add_argument(
        "--canonical-result",
        type=Path,
        default=None,
        help="canonical Design/rtl-design/result.json (absent => first-run)",
    )
    sp.set_defaults(func=_cmd_classify_delta)

    sp = sub.add_parser("finalize", help="assemble the lean result.json")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument("--top", required=True, help="top module (= manifest.module)")
    sp.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Design/specification/manifest.json",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
