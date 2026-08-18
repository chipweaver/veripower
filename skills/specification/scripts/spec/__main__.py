#!/usr/bin/env python3
"""spec — specification-stage CLI.

Verbs (one stage = one tool):
  derive-ports        per-child ports from interconnects.json (stdout: JSON)
  check-crossrefs     cross-file name + orphan join         (stdout: verdict JSON; exit 0/1)
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


def _cmd_derive_ports(a: argparse.Namespace) -> int:
    from spec import ports

    print(json.dumps(ports.derive_ports(a.workdir), ensure_ascii=False, indent=2))
    return 0


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

    return result.finalize(
        a.workdir,
        status=a.status,
        ppa_targets_json=a.ppa_targets,
        fail_reason=a.fail_reason,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spec", description="specification-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("derive-ports", help="per-child §1.4.2 inter-module ports")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_derive_ports)

    sp = sub.add_parser("check-crossrefs", help="cross-file name + orphan join")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_check_crossrefs)

    sp = sub.add_parser("derive-constraints", help="generate SDC/SGDC (fail-loud)")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.set_defaults(func=_cmd_derive_constraints)

    sp = sub.add_parser("finalize", help="assemble the lean result.json")
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--status",
        required=True,
        choices=["pass", "fail"],
        help="the human approve/reject decision at the Step-7 design.md gate; "
        "fail also serves the documented early-fail exits (with --fail-reason)",
    )
    sp.add_argument(
        "--ppa-targets",
        default=None,
        help="optional override: ppa_targets JSON array; default = read the "
        "Wave-1-authored {workdir}/ppa.json from disk",
    )
    sp.add_argument(
        "--fail-reason",
        default=None,
        help="on --status fail: the one-line failure narrative (early-fail entry); "
        "default = the Step-7 human-reject wording",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
