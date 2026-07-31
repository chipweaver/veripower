#!/usr/bin/env python3
"""sim — simulation-stage CLI.

Verbs (one stage = one tool; see skills/simulation/SKILL.md for usage):
  bootstrap             deploy infra + optional scaffold into a run workdir   (exit 0 / 1 / 2)
  render-scaffold       render the UVM scaffold tree from the plan sidecars    (exit 0 / non-zero raise)
  check-materialization thin-D1 presence gate (env-exit self-gate)            (stdout verdict; exit 0/1)
  validate-review       conformance-review.json schema + gate                 (stdout gate JSON; exit 0/1)
  finalize              assemble the lean result.json at the exit phase        (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the sim.*
library. Library imports are deferred into each handler (NOT top-level) so --help
and verb dispatch run during incremental per-task TDD, before the sibling modules
exist. (Library modules themselves use top-level absolute imports; only this thin
dispatcher defers.) NEVER `import _gate` bare inside this package — only `from sim import …`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/simulation/scripts) on sys.path so absolute imports
# `from sim import …` resolve whether this file is run directly
# (python3 …/sim/__main__.py) or via `python3 -m sim`. abspath() is required;
# the double dirname climbs sim/ -> scripts/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from sim import bootstrap

    return bootstrap.run(a.module, a.workdir, scaffold=a.plan)


def _cmd_render_scaffold(a: argparse.Namespace) -> int:
    from sim import scaffold

    return scaffold.render(a.plan, a.output_dir, a.template_dir)


def _cmd_check_materialization(a: argparse.Namespace) -> int:
    from sim import materialization

    return materialization.run(a.workdir, a.plan)


def _cmd_validate_review(a: argparse.Namespace) -> int:
    from sim import review

    return review.validate(a.review)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from sim import result

    if a.phase == "final" and not (a.plan and a.thresholds and a.conformance_review):
        print(
            "[sim finalize] ERROR: --plan, --thresholds and --conformance-review are "
            "required for --phase final",
            file=sys.stderr,
        )
        return 2
    return result.finalize(
        a.workdir,
        a.module,
        phase=a.phase,
        scaffold=a.plan,
        thresholds=a.thresholds,
        conformance_review=a.conformance_review,
        verify_verdict=a.verify_verdict,
        fail_reason=a.fail_reason,
        observed_phase=a.failure_phase,
        fix_owner=a.fix_owner,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sim", description="simulation-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap", help="deploy infra + optional scaffold into a run workdir"
    )
    sp.add_argument("--module", required=True)
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="the simulation-plan workdir (renders the UVM scaffold when given)",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "render-scaffold", help="render the UVM scaffold tree from the plan sidecars"
    )
    sp.add_argument("--plan", required=True, type=Path)
    sp.add_argument("--output-dir", required=True, type=Path)
    sp.add_argument("--template-dir", type=Path, default=None)
    sp.set_defaults(func=_cmd_render_scaffold)

    sp = sub.add_parser(
        "check-materialization", help="thin-D1 presence gate (env-exit self-gate)"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--plan", required=True, type=Path)
    sp.set_defaults(func=_cmd_check_materialization)

    sp = sub.add_parser("validate-review", help="conformance-review.json schema + gate")
    sp.add_argument("--review", required=True, type=Path)
    sp.set_defaults(func=_cmd_validate_review)

    sp = sub.add_parser(
        "finalize", help="assemble the lean result.json at the exit phase"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument(
        "--phase",
        required=True,
        choices=[
            "prerequisite",
            "env-blocked",
            "smoke",
            "conformance",
            "regress",
            "verify-blocked",
            "final",
        ],
    )
    sp.add_argument(
        "--failure-phase",
        choices=[
            "prerequisite",
            "compile",
            "smoke",
            "conformance",
            "regress",
            "coverage",
        ],
        default=None,
        help="observed schema failure_phase when the call-site spans several; defaults per --phase",
    )
    sp.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="the simulation-plan workdir (required for --phase final)",
    )
    sp.add_argument(
        "--thresholds",
        type=Path,
        default=None,
        help="defaults.yaml (required for --phase final)",
    )
    sp.add_argument("--conformance-review", type=Path, default=None)
    sp.add_argument(
        "--verify-verdict", type=Path, default=None, help="reaped verify-child JSON"
    )
    sp.add_argument(
        "--fail-reason", default=None, help="one-line reason for an early-exit phase"
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
