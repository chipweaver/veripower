#!/usr/bin/env python3
"""synthesis — synthesis-stage CLI.

Verbs (one stage = one tool; see skills/synthesis/SKILL.md for usage):
  bootstrap   deploy templates into the run workdir + render rtl_load/config  (exit 0 / 1 / 2)
  finalize    parse DC reports, judge PPA, assemble the result.json           (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
synthesis.* library. Library imports are deferred into each handler so they run
AFTER the sys.path insert below, which is what makes `from synthesis import …`
resolve at all. (Library modules themselves use top-level absolute imports; only
this thin dispatcher defers.)
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Put the package PARENT (…/synthesis/scripts) on sys.path so absolute imports
# `from synthesis import …` resolve whether this file is run directly
# (python3 …/synthesis/__main__.py) or via `python3 -m synthesis`. abspath() is
# required; the double dirname climbs synthesis/ -> scripts/. NEVER `import result`
# bare inside this package — only `from synthesis import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


GATED_DIMS = ("area_um2", "timing_slack_ns")  # power_mw is judged in power-analysis


def read_ppa_targets(workdir) -> dict:
    """{dim: target} for the two dims this stage gates, from the specification ppa.json
    it binds to as its acceptance standard. The stage root comes from the injected
    `<workdir>/dispatch.json` `inputs."ppa"`, not self-navigation. An absent file or dim
    leaves that dimension ungated."""
    inputs = json.loads((Path(workdir) / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]
    p = Path(inputs["ppa"]) / "ppa.json"
    if not p.is_file():
        return {}
    return {
        t["dim"]: t["target"]
        for t in json.loads(p.read_text())
        if t.get("dim") in GATED_DIMS
    }


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from synthesis import bootstrap

    return bootstrap.run(a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from synthesis import result

    targets = read_ppa_targets(a.workdir)
    return result.finalize(
        a.workdir,
        a.module,
        targets.get("area_um2"),
        targets.get("timing_slack_ns"),
        a.fix_owner,
        a.fail_reason,
        a.failure_kind,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="synthesis", description="synthesis-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap", help="deploy templates + render rtl_load/config into the workdir"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; read from the specification manifest when omitted",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    sp = sub.add_parser(
        "finalize", help="parse DC reports, judge PPA, assemble result.json"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument("--module", required=True)
    sp.add_argument(
        "--fix-owner",
        default=None,
        help="on a failure, the rule that must act (you name it; the reports cannot)",
    )
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="cause of a run with no gradeable reports (license, elaborate/compile "
        "abort, crash after reporting); supplying it declares the failure and wins "
        "over the gate. Needs --failure-kind.",
    )
    sp.add_argument(
        "--failure-kind",
        default=None,
        choices=("infra", "tooling"),
        help="with --fail-reason: infra = DC never ran, tooling = DC ran and its "
        "output is unusable (ppa is the gate's to write, never yours)",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
