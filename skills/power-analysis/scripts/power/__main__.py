#!/usr/bin/env python3
"""Power experiment setup, execution, calculation and closure."""

import argparse
import json
import os
import sys
from pathlib import Path

# Put the package PARENT (…/power-analysis/scripts) on sys.path so absolute
# imports `from power import …` resolve whether this file is run directly
# (python3 …/power/__main__.py) or via `python3 -m power`. abspath() is
# required; the double dirname climbs power/ -> scripts/. NEVER `import result`
# bare inside this package — only `from power import …`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _inputs(workdir) -> dict:
    """The injected `inputs` table from `<workdir>/dispatch.json`. Every upstream
    location this stage reads is in here, so none of them is a path the caller types."""
    return json.loads((Path(workdir) / "dispatch.json").read_text(encoding="utf-8"))[
        "inputs"
    ]


def _cmd_bootstrap(a: argparse.Namespace) -> int:
    from power import bootstrap

    return bootstrap.run(a.workdir, top=a.top)


def _cmd_finalize(a: argparse.Namespace) -> int:
    (Path(a.workdir) / "result.json").unlink(missing_ok=True)
    from power import requirements, result

    return result.finalize(
        a.workdir,
        _inputs(a.workdir)["plan"],
        requirements.mine(requirements.load(a.workdir)),
        requirements.parse_declared(a.requirements),
        a.fix_owner,
        a.fail_reason,
    )


def _cmd_execute(a):
    from power.execute import run

    return run(a.workdir, a.cmd)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="power", description="power-analysis-stage CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "bootstrap", help="prepare editable setup; execution checks its own inputs"
    )
    sp.add_argument("--workdir", required=True, type=Path)
    sp.add_argument(
        "--top",
        default=None,
        help="top module; inferred from the injected synthesis netlist's out/<TOP>_syn.v when omitted",
    )
    sp.set_defaults(func=_cmd_bootstrap)

    for mode in ("compile", "simulate", "calculate"):
        sp = sub.add_parser(mode)
        sp.add_argument("--workdir", required=True, type=Path)
        sp.set_defaults(func=_cmd_execute)

    sp = sub.add_parser(
        "finalize", help="parse PT-PX reports, judge power_mw PPA, assemble result.json"
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
        help="unresolved reason the measurement is invalid or incomplete, even if reports "
        "contain numbers; declares failure without qualifying those measurements",
    )
    sp.add_argument(
        "--requirements",
        default=None,
        help="judgments for power-analysis rows without numeric targets: JSON array entries "
        "require id, met and measured; actual is optional. Numeric targets are computed",
    )
    sp.set_defaults(func=_cmd_finalize)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(
            f"[power {args.cmd}] BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
