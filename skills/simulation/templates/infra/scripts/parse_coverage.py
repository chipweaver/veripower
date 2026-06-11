#!/usr/bin/env python3
"""Parse the urg text coverage report into structural-coverage.json (deployed infra).

Consumes cov_merge/dashboard.txt (aggregate) + cov_merge/modlist.txt (per-module),
the text report urg emits with `-report cov_merge -format text`. Column order is
fixed: SCORE LINE COND TOGGLE FSM BRANCH. '--' means the dim does not apply to that
scope -> None (e.g. a module with no FSM). Fail-loud (SystemExit) when the report is
missing or the aggregate block is unparseable -- NEVER emit a file that could be read
as 'coverage met'.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Header column order in urg L-2016.06 text reports.
_DIM_ORDER = ["score", "line", "cond", "toggle", "fsm", "branch"]


def _num(tok: str):
    """'--' / 'n/a' -> None; otherwise float."""
    return None if tok in ("--", "n/a", "") else float(tok)


def _values_after_header(lines: list[str], start: int) -> dict | None:
    """Given a 'SCORE LINE COND ... ' header at lines[start], parse the next
    non-empty line of 6 leading numeric/-- tokens into the dim dict."""
    for ln in lines[start + 1 :]:
        toks = ln.split()
        if len(toks) >= len(_DIM_ORDER) and re.match(r"^[\d.]+$|^--$", toks[0]):
            return {d: _num(t) for d, t in zip(_DIM_ORDER, toks[: len(_DIM_ORDER)])}
    return None


def parse_aggregate(text: str) -> dict | None:
    """Aggregate dims from the 'Total Coverage Summary' block. None if absent."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Total Coverage Summary"):
            # next line is the SCORE LINE COND ... header
            for j in range(i + 1, min(i + 4, len(lines))):
                if "SCORE" in lines[j] and "LINE" in lines[j]:
                    return _values_after_header(lines, j)
    return None


def parse_modules(text: str) -> list[dict]:
    """Per-module rows from modlist.txt: 6 dim tokens + trailing module name."""
    out: list[dict] = []
    lines = text.splitlines()
    in_table = False
    for ln in lines:
        if "SCORE" in ln and "LINE" in ln and "NAME" in ln:
            in_table = True
            continue
        if not in_table:
            continue
        toks = ln.split()
        if len(toks) < len(_DIM_ORDER) + 1:
            continue
        if not re.match(r"^[\d.]+$|^--$", toks[0]):
            continue
        row = {d: _num(t) for d, t in zip(_DIM_ORDER, toks[: len(_DIM_ORDER)])}
        row["name"] = toks[len(_DIM_ORDER)]
        out.append(row)
    return out


def _urg_version(text: str) -> str:
    m = re.search(r"Version:\s*(\S+)", text)
    return m.group(1) if m else ""


def build(cov_dir: Path, out_path: Path) -> int:
    dashboard = cov_dir / "dashboard.txt"
    if not dashboard.is_file():
        sys.exit(
            f"parse_coverage: missing {dashboard}. urg merge did not produce a text report "
            f"(run `make merge` / check VCS_COV and urg). NOT emitting structural-coverage.json "
            f"(fail-loud: never claim coverage met when it cannot be measured)."
        )
    dtext = dashboard.read_text(encoding="utf-8", errors="ignore")
    agg = parse_aggregate(dtext)
    if agg is None:
        sys.exit(
            f"parse_coverage: could not parse aggregate coverage from {dashboard} "
            f"(urg text format may differ on this version: {_urg_version(dtext)!r}). "
            f"Fix parse_coverage for this urg version; NOT emitting structural-coverage.json."
        )
    modlist = cov_dir / "modlist.txt"
    per_module = (
        parse_modules(modlist.read_text(encoding="utf-8", errors="ignore"))
        if modlist.is_file()
        else []
    )
    data = {
        "aggregate": agg,
        "per_module": per_module,
        "source": str(dashboard),
        "urg_version": _urg_version(dtext),
    }
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(
        f"parse_coverage: wrote {out_path} "
        f"(line={agg['line']} cond={agg['cond']} fsm={agg['fsm']} toggle={agg['toggle']})"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="urg text report -> structural-coverage.json"
    )
    p.add_argument(
        "--cov-dir",
        required=True,
        help="urg report dir (contains dashboard.txt/modlist.txt)",
    )
    p.add_argument("--out", required=True, help="output structural-coverage.json path")
    args = p.parse_args()
    return build(Path(args.cov_dir).resolve(), Path(args.out).resolve())


if __name__ == "__main__":
    sys.exit(main())
