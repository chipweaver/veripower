#!/usr/bin/env python3
"""sim — simulation-stage CLI.

Verbs (one stage = one tool):
  bootstrap             deploy infra + optional scaffold into a run workdir   (exit 0 / 1 / 2)
  check-materialization presence gate over the materialized TB (env-exit self-gate) (stdout verdict; exit 0/1)
  finalize              write result.json (--phase fail | final)              (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the sim.*
library. Library imports are deferred into each handler rather than taken at the top so
that --help and verb dispatch keep working when one library has an import-time problem;
the library modules themselves import absolutely at the top. NEVER `import _gate` bare
inside this package, only `from sim import …`.
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

    return bootstrap.run(a.workdir, scaffold=a.plan)


def _cmd_check_materialization(a: argparse.Namespace) -> int:
    from sim import materialization

    return materialization.run(a.workdir, a.plan)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from sim import result

    if a.phase == "final" and not (a.plan and a.requirements and a.conformance_review):
        print(
            "[sim finalize] ERROR: --plan, --requirements and --conformance-review are "
            "required for --phase final",
            file=sys.stderr,
        )
        return 2
    # A fail envelope whose reason is empty is rejected by the envelope schema at reap, which
    # costs the round a blocked outcome instead of a routable fail. Refuse here, loudly, rather
    # than write one: the caller always holds a reason — the child's BLOCKED line, or the
    # failing case it just read.
    if a.phase == "fail" and not (a.fail_reason and a.fail_reason.strip()):
        print(
            "[sim finalize] ERROR: --fail-reason is required for --phase fail",
            file=sys.stderr,
        )
        return 2
    return result.finalize(
        a.workdir,
        phase=a.phase,
        scaffold=a.plan,
        requirements=a.requirements,
        conformance_review=a.conformance_review,
        verify_verdict=a.verify_verdict,
        fail_reason=a.fail_reason,
        fix_owner=a.fix_owner,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sim", description="simulation-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap", help="deploy infra + optional scaffold into a run workdir"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="the simulation-plan workdir (renders the UVM scaffold when given)",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "check-materialization",
        help="presence gate over the materialized TB (env-exit self-gate)",
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--plan", required=True, type=Path)
    sp.set_defaults(func=_cmd_check_materialization)

    sp = sub.add_parser("finalize", help="write result.json (--phase fail | final)")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--phase",
        required=True,
        choices=["fail", "final"],
        help="`fail` closes the round on a failure the caller already holds a reason for; "
        "`final` re-runs the three exit gates. Which sub-step tripped is not a flag: it is "
        "what --fail-reason says, and which companions ride along follows from what the "
        "reaped verify verdict actually carries.",
    )
    sp.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="the simulation-plan workdir (required for --phase final)",
    )
    sp.add_argument(
        "--requirements",
        type=Path,
        default=None,
        help="the specification requirements.json; its coverage bounds judged by simulation "
        "are the coverage gate (required for --phase final)",
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
