#!/usr/bin/env python3
"""Render README.md (Top-module line + SGDC/SDC constraint-annotation note) from the ledger.

Consumers (LLM-read): lint-cdc reads the SGDC section (sync_cell / reset_synchronizer /
set_case_analysis / quasi_static); synthesis reads the SDC section (create_generated_clock /
set_multicycle_path / set_false_path). The '**Top module**: <X>' line is *pattern-grepped*
by their bootstrap scripts — keep it byte-stable.

Usage: build_readme.py --ledger <.child_reports.json> --top <top_module> --out <workdir/README.md>
Exit: non-zero + stderr on malformed ledger (fail-loud).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
from ledger_io import LedgerError, load_ledger  # noqa: E402


def _agg(ledger: dict, family: str, key: str) -> list:
    items: list = []
    for name in sorted(ledger):
        items.extend(ledger[name]["annotations"].get(family, {}).get(key, []))
    return items


def render(ledger: dict, top: str) -> str:
    sync = _agg(ledger, "sgdc", "sync_cell")
    rsync = _agg(ledger, "sgdc", "reset_synchronizer")
    sca = _agg(ledger, "sgdc", "set_case_analysis")
    qs = _agg(ledger, "sgdc", "quasi_static")
    gc = _agg(ledger, "sdc", "create_generated_clock")
    mcp = _agg(ledger, "sdc", "set_multicycle_path")
    fp = _agg(ledger, "sdc", "set_false_path")

    lines = [
        f"**Top module**: {top}",
        "",
        "## Constraint-annotation note",
        "",
        "### SGDC",
        "",
    ]
    if not (sync or rsync or sca or qs):
        lines.append("single clock domain; no deep annotations needed.")
    else:
        lines += [f"- sync_cell -name {m}" for m in sync]
        lines += [f"- reset_synchronizer -name {m}" for m in rsync]
        lines += [f"- set_case_analysis {e['value']} {e['port']}" for e in sca]
        lines += [f"- quasi_static -name {s}" for s in qs]

    lines += ["", "### SDC", ""]
    gc_str = "; ".join(f"{g['module']}.{g['pin']}" for g in gc) if gc else "none"
    lines.append(f"- create_generated_clock: {gc_str}")
    lines.append(f"- set_multicycle_path: {'; '.join(mcp) if mcp else 'none'}")
    lines.append(f"- set_false_path: {'; '.join(fp) if fp else 'none'}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", required=True, type=Path)
    ap.add_argument("--top", required=True)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    try:
        ledger = load_ledger(a.ledger)
    except LedgerError as e:
        print(f"build_readme: {e}", file=sys.stderr)
        return 1
    a.out.write_text(render(ledger, a.top), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
