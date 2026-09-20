#!/usr/bin/env python3
"""Command-line operations for the spec stage."""

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spec", description="specification-stage CLI")
    subcommands = parser.add_subparsers(dest="cmd", required=True)

    command_parser = subcommands.add_parser(
        "check-ledger",
        help="validate requirements.json and show decisions, external scope and numerical targets",
    )
    command_parser.add_argument("--workdir", required=True, type=Path)

    command_parser = subcommands.add_parser(
        "check-crossrefs", help="hint↔requirement join + phantom clock domain"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)

    command_parser = subcommands.add_parser(
        "derive-constraints", help="generate SDC/SGDC (fail-loud)"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)

    command_parser = subcommands.add_parser(
        "finalize", help="assemble the lean result.json"
    )
    command_parser.add_argument("--workdir", required=True, type=Path)
    command_parser.add_argument(
        "--fail-reason",
        default=None,
        help="the one-line reason this round could not deliver; its presence is the failure. "
        "Absent = the stage delivered what it owes",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from spec.sidecar import SidecarError

    try:
        if args.cmd == "check-ledger":
            from spec import ledger

            return ledger.run(args.workdir)
        elif args.cmd == "check-crossrefs":
            from spec import crossrefs

            verdict = crossrefs.verdict(args.workdir)
            print(json.dumps(verdict, ensure_ascii=False, indent=2))
            return 0 if verdict["status"] == "pass" else 1
        elif args.cmd == "derive-constraints":
            from spec import constraints

            print(
                json.dumps(
                    constraints.derive_constraints(args.workdir),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        else:
            from spec import result

            return result.finalize(args.workdir, fail_reason=args.fail_reason)
    except (OSError, ValueError, SidecarError) as error:
        print(f"[spec {args.cmd}] BLOCKED: {error}", file=sys.stderr)
        return 2 if args.cmd == "finalize" else 1


if __name__ == "__main__":
    sys.exit(main())
