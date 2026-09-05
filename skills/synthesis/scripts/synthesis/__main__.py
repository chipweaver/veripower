#!/usr/bin/env python3
"""synthesis — synthesis-stage CLI.

Verbs (one stage = one tool):
  bootstrap   deploy templates into the run workdir + render rtl_load/config  (exit 0 / 1 / 2)
  finalize    parse DC reports, judge PPA, assemble the result.json           (exit 0 written / 2 BLOCKED)

Thin dispatcher: each subcommand parses its own flags and calls into the
synthesis.* library. Library imports are deferred into each handler so they run
AFTER the sys.path insert below, which is what makes `from synthesis import …`
resolve at all. (Library modules themselves use top-level absolute imports; only
this thin dispatcher defers.)
"""

import argparse
import os
import sys
from pathlib import Path

# Put the package PARENT (…/synthesis/scripts) on sys.path so absolute imports
# `from synthesis import …` resolve whether this file is run directly
# (python3 …/synthesis/__main__.py) or via `python3 -m synthesis`. abspath() is
# required; the double dirname climbs synthesis/ -> scripts/. NEVER `import result`
# bare inside this package — only `from synthesis import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from synthesis import bootstrap

    return bootstrap.run(a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    from synthesis import requirements, result

    return result.finalize(
        a.workdir,
        requirements.mine(requirements.load(a.workdir)),
        requirements.parse_declared(a.requirements),
        a.fix_owner,
        a.fail_reason,
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
        "over the gate.",
    )
    sp.add_argument(
        "--requirements",
        default=None,
        help="your verdict on each requirements.json row judged by synthesis that carries no "
        'target, as a JSON array of {"id", "met", "actual"}; rows with a target are compared here',
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        # The documented protocol is a reason on stderr and a non-zero exit. A traceback is
        # not that: it answers with source, which every skill here tells the reader never to
        # open. The verbs' own refusals keep their own exits; this is only the unexpected.
        print(
            f"[synthesis {args.cmd}] BLOCKED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
