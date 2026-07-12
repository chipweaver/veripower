#!/usr/bin/env python3
"""simplan — simulation-plan-stage CLI.

Verbs (one stage = one tool; see skills/simulation-plan/SKILL.md for usage):
  derive-plan-data      spec workdir -> plan-data.json          (writes file; exit 0; fail-loud)
  materialize-scaffold  fill scaffold signals/clock/reset/inline (writes scaffold; exit 0; fail-loud)
  check-scaffold        structural+semantic+coverage gate        (exit 0 OK / 1 fix-message)
  validate-review       plan-review.json schema + gate           (stdout: gate JSON; exit 0/1)
  classify-delta        freeze-branch selector                   (stdout: verdict JSON; exit 0/1)
  seed                  carry prior canonical plan products fwd (whitelist) (stdout: JSON; exit 0)
  finalize              assemble the lean result.json            (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the simplan.*
library. Library imports are deferred into each handler (NOT top-level) so --help
and verb dispatch run during incremental per-task TDD, before the sibling modules
exist. A top-level `from simplan import plan_data, materialize, …` would ImportError
until every verb is built. Keep them lazy. (Library modules themselves use top-level
absolute imports; only this thin dispatcher defers.)
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


def _cmd_derive_plan_data(a: argparse.Namespace) -> int:
    from simplan import plan_data

    return plan_data.run(a.workdir, a.output)


def _cmd_materialize_scaffold(a: argparse.Namespace) -> int:
    from simplan import materialize

    return materialize.run(a.plan_data, a.scaffold)


def _cmd_check_scaffold(a: argparse.Namespace) -> int:
    from simplan import scaffold

    return scaffold.run(a.scaffold, a.plan_data, a.schema)


def _cmd_validate_review(a: argparse.Namespace) -> int:
    from simplan import review

    return review.validate(a.review)


def _cmd_classify_delta(a: argparse.Namespace) -> int:
    from simplan import classify

    return classify.run(a.canonical_result, a.spec_dir)


def _cmd_seed(a: argparse.Namespace) -> int:
    from simplan import seed

    return seed.run(a.workdir, a.canonical, freeze=a.freeze)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from simplan import result

    return result.finalize(
        a.workdir,
        a.module,
        waived_json=a.waived,
        status=a.status,
        revision=a.revision,
        fail_reason=a.fail_reason,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="simplan", description="simulation-plan-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("derive-plan-data", help="spec workdir -> plan-data.json")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--output",
        type=Path,
        default=None,
        help="direct output path (default: {workdir}/plan-data.json)",
    )
    sp.set_defaults(func=_cmd_derive_plan_data)

    sp = sub.add_parser(
        "materialize-scaffold",
        help="fill scaffold agent signals / clock / reset / inline hints",
    )
    sp.add_argument("--plan-data", required=True, type=Path)
    sp.add_argument("--scaffold", required=True, type=Path)
    sp.set_defaults(func=_cmd_materialize_scaffold)

    sp = sub.add_parser("check-scaffold", help="structural + semantic + coverage gate")
    sp.add_argument("--scaffold", required=True, type=Path)
    sp.add_argument("--plan-data", required=True, type=Path)
    sp.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="optional schema override (default: sibling references/)",
    )
    sp.set_defaults(func=_cmd_check_scaffold)

    sp = sub.add_parser("validate-review", help="plan-review.json schema + gate")
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
        help="canonical Verification/simulation-plan/result.json (absent => first-run)",
    )
    sp.set_defaults(func=_cmd_classify_delta)

    sp = sub.add_parser(
        "seed",
        help="carry prior canonical plan products forward (whitelist, no-clobber; "
        "never result.json/plan-data.json)",
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
        help="freeze branch only: additionally byte-carry plan-review.json (keeps its pin alive)",
    )
    sp.set_defaults(func=_cmd_seed)

    sp = sub.add_parser("finalize", help="assemble the lean result.json")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument("--waived", default=None, help="JSON array of human waiver objects")
    sp.add_argument(
        "--status",
        choices=["pass", "fail"],
        default=None,
        help="human Step-5 verdict; fail = user reject, or a documented "
        "early-fail exit (with --fail-reason)",
    )
    sp.add_argument(
        "--revision", default=None, help="agent-composed revision narrative"
    )
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="on --status fail: the one-line failure narrative (early-fail entry); "
        "default = the Step-5 user-reject wording",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
