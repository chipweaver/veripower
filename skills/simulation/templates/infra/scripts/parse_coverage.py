#!/usr/bin/env python3
"""Parse the urg text coverage report into structural-coverage.json (deployed infra).

Consumes cov_merge/dashboard.txt (aggregate) + cov_merge/modlist.txt (per-module) +
cov_merge/modinfo.txt (the named uncovered items), the text report urg emits with
`-report cov_merge -format text`. Column order is fixed: SCORE LINE COND TOGGLE FSM
BRANCH. '--' means the dim does not apply to that scope -> None (e.g. a module with no
FSM). Fail-loud (SystemExit) when the report is missing or the aggregate block is
unparseable -- NEVER emit a file that could be read as 'coverage met'.

A percentage says how much was missed; `uncovered[]` says WHICH branch, condition or
FSM transition was missed, by module and source line. urg computes it either way -- a
percentage is the only thing a reader can act on if the items are dropped, and
'mgpt_rmsnorm.v:160 branch (div_q > QMAX) never taken' is actionable where '85.71%' is
not. modinfo.txt is optional: absent (or a urg version whose format differs) yields an
empty list, never a failure -- the gate contract stays on `aggregate`.
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


# ── modinfo.txt: the named uncovered items ─────────────────────────
#
# Three section shapes, one per metric (urg L-2016.06):
#
#   Branch  annotated source with `-N-` markers under each branch, then a wide
#           `-1- -2- ... -N- Status` table; a `Not Covered` row's LAST non-'-' marker
#           is the leaf that was never taken (the earlier ones are covered by other
#           rows), so that marker's source line is the locus.
#   Cond    ` LINE <n>` + ` EXPRESSION <text>` + a small `-1- Status` table.
#   FSM     `<state-or-transition>  <line>  Covered|Not Covered` rows.
_MODULE_RE = re.compile(r"^Module : (\S+)")
_SECTION_RE = re.compile(r"^(Branch|Cond|FSM|Line|Toggle) Coverage for Module : (\S+)")
_SRC_RE = re.compile(r"^\s*(\d+)\s{2,}(\S.*?)\s*$")
_MARKER_RE = re.compile(r"^-\d+-$")
_COND_LINE_RE = re.compile(r"^\s*LINE\s+(\d+)\s*$")
#   urg emits both EXPRESSION and SUB-EXPRESSION blocks (a nested term of the same
#   construct, at its own LINE); both carry their own Status table, so both count.
_COND_EXPR_RE = re.compile(r"^\s*(?:SUB-)?EXPRESSION\s+(\S.*?)\s*$")
_FSM_ROW_RE = re.compile(r"^(\S+)\s+(\d+)\s+(Not Covered|Covered)\s*$")


def _status_of(toks: list[str]) -> tuple[str | None, list[str]]:
    """Split a trailing Covered / 'Not Covered' status off a row's tokens."""
    if len(toks) >= 2 and toks[-2:] == ["Not", "Covered"]:
        return "Not Covered", toks[:-2]
    if toks and toks[-1] == "Covered":
        return "Covered", toks[:-1]
    return None, toks


def parse_uncovered(text: str) -> list[dict]:
    """Named uncovered branch / condition / FSM-transition items from modinfo.txt.

    Best-effort and total: an unrecognised section contributes nothing rather than
    raising, so a urg format change degrades to an empty list (the percentages, and
    therefore the gate, are unaffected).
    """
    items: list[dict] = []
    module: str | None = None
    kind: str | None = None
    marker_line: dict[str, int] = {}  # '-21-' -> source line no
    src_text: dict[int, str] = {}  # line no -> source text
    last_src: int | None = None
    header: list[str] = []  # ordered markers of the current status table
    cond_line: int | None = None
    cond_expr: str | None = None

    def reset_section() -> None:
        nonlocal marker_line, src_text, last_src, header, cond_line, cond_expr
        marker_line, src_text, last_src, header = {}, {}, None, []
        cond_line, cond_expr = None, None

    for raw in text.splitlines():
        m = _MODULE_RE.match(raw)
        if m:
            module, kind = m.group(1), None
            reset_section()
            continue
        m = _SECTION_RE.match(raw)
        if m:
            kind = {"Branch": "branch", "Cond": "cond", "FSM": "fsm"}.get(m.group(1))
            module = m.group(2)
            reset_section()
            continue
        if kind is None or module is None:
            continue
        toks = raw.split()
        if not toks:
            continue

        if kind == "branch":
            if toks and all(_MARKER_RE.match(t) for t in toks):
                if last_src is not None:
                    for t in toks:
                        marker_line.setdefault(t, last_src)
                continue
            if toks[-1] == "Status" and any(_MARKER_RE.match(t) for t in toks):
                header = [t for t in toks if _MARKER_RE.match(t)]
                continue
            if header:
                status, vals = _status_of(toks)
                if status is not None and len(vals) == len(header):
                    taken = [h for h, v in zip(header, vals) if v != "-"]
                    if status == "Not Covered" and taken:
                        ln = marker_line.get(taken[-1])
                        items.append(
                            {
                                "module": module,
                                "kind": "branch",
                                "line": ln,
                                "detail": src_text.get(ln, taken[-1]),
                            }
                        )
                    continue
            m = _SRC_RE.match(raw)
            if m and not all(t in ("0", "1", "-") for t in toks[1:]):
                last_src = int(m.group(1))
                src_text[last_src] = m.group(2)
            continue

        if kind == "cond":
            m = _COND_LINE_RE.match(raw)
            if m:
                cond_line, cond_expr = int(m.group(1)), None
                continue
            m = _COND_EXPR_RE.match(raw)
            if m:
                cond_expr = m.group(1)
                continue
            status, vals = _status_of(toks)
            if status == "Not Covered" and cond_expr is not None:
                items.append(
                    {
                        "module": module,
                        "kind": "cond",
                        "line": cond_line,
                        "detail": cond_expr,
                    }
                )
            continue

        if kind == "fsm":
            m = _FSM_ROW_RE.match(raw.strip())
            if m and m.group(3) == "Not Covered":
                items.append(
                    {
                        "module": module,
                        "kind": "fsm",
                        "line": int(m.group(2)),
                        "detail": m.group(1),
                    }
                )
            continue

    # urg repeats some detail blocks; dedupe and order deterministically.
    seen, uniq = set(), []
    for it in items:
        k = (it["module"], it["kind"], it["line"], it["detail"])
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    uniq.sort(key=lambda i: (i["module"], i["kind"], i["line"] or 0, i["detail"]))
    return uniq


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
    modinfo = cov_dir / "modinfo.txt"
    uncovered = (
        parse_uncovered(modinfo.read_text(encoding="utf-8", errors="ignore"))
        if modinfo.is_file()
        else []
    )
    data = {
        "aggregate": agg,
        "per_module": per_module,
        "uncovered": uncovered,
        "source": str(dashboard),
        "urg_version": _urg_version(dtext),
    }
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(
        f"parse_coverage: wrote {out_path} "
        f"(line={agg['line']} cond={agg['cond']} fsm={agg['fsm']} toggle={agg['toggle']}"
        f"; {len(uncovered)} uncovered items)"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="urg text report -> structural-coverage.json"
    )
    p.add_argument(
        "--cov-dir",
        required=True,
        help="urg report dir (contains dashboard.txt/modlist.txt/modinfo.txt)",
    )
    p.add_argument("--out", required=True, help="output structural-coverage.json path")
    args = p.parse_args()
    return build(Path(args.cov_dir).resolve(), Path(args.out).resolve())


if __name__ == "__main__":
    sys.exit(main())
