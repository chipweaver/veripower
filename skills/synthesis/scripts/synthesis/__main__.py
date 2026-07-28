#!/usr/bin/env python3
"""synthesis — synthesis-stage CLI.

Verbs (one stage = one tool; see skills/synthesis/SKILL.md for usage):
  bootstrap   deploy templates into the run workdir + render rtl_load/config  (exit 0 / 1 / 2)
  finalize    parse DC reports, judge PPA, assemble the lean result.json      (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
synthesis.* library. Library imports are deferred into each handler (NOT
top-level) so --help and verb dispatch run during incremental per-task TDD,
before the sibling modules (bootstrap.py / result.py) exist. A top-level
`from synthesis import bootstrap, result` would ImportError until both verbs
are built. Keep them lazy. (Library modules themselves use top-level absolute
imports; only this thin dispatcher defers.)
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


def _read_ppa_targets(workdir, dims: set[str]) -> list:
    """PPA targets from the specification stage root's ppa.json sidecar (spec
    §4.3) — filtered to `dims` — replacing the old injected
    --area-target/--slack-target CLI args (synthesis binds to this file as its
    acceptance standard). The stage root comes from the injected
    `<workdir>/inputs.json` "ppa" key, not self-navigation."""
    inputs = json.loads((Path(workdir) / "inputs.json").read_text(encoding="utf-8"))
    p = Path(inputs["ppa"]) / "ppa.json"
    if not p.is_file():
        return []
    return [t for t in json.loads(p.read_text()) if t.get("dim") in dims]


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from synthesis import bootstrap

    return bootstrap.run(a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from synthesis import result

    targets = _read_ppa_targets(a.workdir, {"area_um2", "timing_slack_ns"})
    area_target = next((t["target"] for t in targets if t["dim"] == "area_um2"), None)
    slack_target = next(
        (t["target"] for t in targets if t["dim"] == "timing_slack_ns"), None
    )
    return result.finalize(a.workdir, a.module, a.top, area_target, slack_target)


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
        "--top", required=True, help="top module (required; finalize cannot infer it)"
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
