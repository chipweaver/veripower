#!/usr/bin/env python3
"""spec — specification-stage CLI.

Verbs (one stage = one tool; see skills/specification/SKILL.md for usage):
  derive-ports        per-child §1.4.2 inter-module ports   (stdout: JSON)
  check-coverage      manifest-driven coverage gate         (stdout: verdict JSON; exit 0/1)
  derive-constraints  generate SDC/SGDC from §1.6 + §1.4.1  (stdout: JSON; fail-loud)
  validate-review     spec-review.json schema + gate        (stdout: gate JSON; exit 0/1)
  finalize            assemble the lean result.json         (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
spec.* library. Library imports are deferred into each handler (NOT top-level)
for two reasons: (1) the entry module loads cheaply and stays decoupled; and
(2) — the load-bearing reason when this template is copied per stage — it lets
`--help` and verb dispatch run before the sibling library modules exist. A
top-level `from spec import coverage, ports, …` would ImportError until every
verb's library is built.
Keep them lazy. (Library modules themselves use top-level absolute imports;
only this thin dispatcher defers.)
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Put the package PARENT (…/specification/scripts) on sys.path so absolute
# imports `from spec import …` resolve whether this file is run directly
# (python3 …/spec/__main__.py) or via `python3 -m spec`. abspath() is required;
# the double dirname climbs spec/ -> scripts/. NEVER `import coverage` bare
# inside this package — only `from spec import …` (a bare name binds the
# top-level slot and collides across stages).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_derive_ports(a: argparse.Namespace) -> int:
    from spec import ports

    print(json.dumps(ports.derive_ports(a.workdir), ensure_ascii=False, indent=2))
    return 0


def _cmd_check_coverage(a: argparse.Namespace) -> int:
    from spec import coverage

    return coverage.run(a.workdir, a.brainstorm)


def _cmd_derive_constraints(a: argparse.Namespace) -> int:
    from spec import constraints

    print(
        json.dumps(
            constraints.derive_constraints(a.workdir), ensure_ascii=False, indent=2
        )
    )
    return 0


def _cmd_validate_review(a: argparse.Namespace) -> int:
    from spec import review

    return review.validate(a.review)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from spec import result

    return result.finalize(
        a.workdir,
        a.module,
        status=a.status,
        ppa_targets_json=a.ppa_targets,
        waived_json=a.waived,
        fail_reason=a.fail_reason,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spec", description="specification-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("derive-ports", help="per-child §1.4.2 inter-module ports")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_derive_ports)

    sp = sub.add_parser("check-coverage", help="manifest-driven coverage gate")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--brainstorm",
        required=True,
        type=Path,
        help="module-root brainstorm.md, passed explicitly because it lives outside the workdir",
    )
    sp.set_defaults(func=_cmd_check_coverage)

    sp = sub.add_parser("derive-constraints", help="generate SDC/SGDC (fail-loud)")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_derive_constraints)

    sp = sub.add_parser("validate-review", help="spec-review.json schema + gate")
    sp.add_argument("--review", required=True, type=Path)
    sp.set_defaults(func=_cmd_validate_review)

    sp = sub.add_parser("finalize", help="assemble the lean result.json")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument(
        "--status",
        required=True,
        choices=["pass", "fail"],
        help="the human approve/reject decision at the Step-8 design.md gate; "
        "fail also serves the documented early-fail exits (with --fail-reason)",
    )
    sp.add_argument(
        "--ppa-targets",
        default=None,
        help="optional override: ppa_targets JSON array; default = read the "
        "Wave-1-authored {workdir}/ppa.json from disk",
    )
    sp.add_argument(
        "--waived",
        default="[]",
        help="human-waiver JSON array recorded at the Step-8 gate",
    )
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="on --status fail: the one-line failure narrative (early-fail entry); "
        "default = the Step-8 human-reject wording",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
