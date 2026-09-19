#!/usr/bin/env python3
"""Parse the urg text coverage report into structural-coverage.json (deployed infra).

Consumes dashboard.txt (aggregate) and modinfo.txt (instance subtrees and uncovered
items) from `urg -format text`. Each per_instance row is an "Instance's subtree"
table keyed by its full instance path, including instantiated RTL below that path.
Columns come from each table's header. '--' becomes None: the report alone does not
establish whether the metric is inapplicable or instrumentation is missing.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# urg prints its column names above every table, and which columns it prints follows the
# `-metric` it was run with. Reading them beats assuming a set: a report produced without
# branch coverage has five columns, and a parser expecting six walks past the row it wants
# and latches onto the next block's — on a real OpenTitan run that put an instance NAME
# where a number belonged. So the header is the schema, and a dim urg did not measure is
# simply absent, which is what the coverage gate already answers ("urg measured none").


def _num(tok: str):
    """'--' / 'n/a' -> None; otherwise float."""
    if tok in ("--", "n/a"):
        return None
    value = float(tok)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError(f"invalid coverage percentage: {tok}")
    return value


def _dims(header: str) -> list[str]:
    """The dim column names this table declares, lowercased, NAME excluded."""
    return [t.lower() for t in header.split() if t.upper() != "NAME"]


def _values_after_header(lines: list[str], start: int) -> dict | None:
    """The first row under the header at lines[start] that has exactly the columns the
    header declares. A row with a different count belongs to another block, not this one."""
    dims = _dims(lines[start])
    for ln in lines[start + 1 :]:
        toks = ln.split()
        if not toks:
            continue
        if len(toks) == len(dims) and re.match(r"^[\d.]+$|^--$", toks[0]):
            return dict(zip(dims, (_num(t) for t in toks)))
        return None
    return None


def parse_aggregate(text: str) -> dict | None:
    """Aggregate dims from the 'Total Coverage Summary' block. None if absent."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("Total Coverage Summary"):
            # The next table declares whichever metrics URG reported.
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].split()[:1] == ["SCORE"]:
                    return _values_after_header(lines, j)
    return None


def parse_instances(text: str) -> list[dict]:
    """Read URG's subtree measurements, never module or instance-self tables."""
    out: list[dict] = []
    names = set()
    for block in re.split(r"(?=^Module(?: Instance)? : \S)", text, flags=re.M):
        match = re.match(r"Module Instance : (\S+)", block)
        if not match:
            continue
        name = match.group(1)
        if name in names:
            raise ValueError(f"duplicate coverage instance: {name}")
        names.add(name)
        lines = block.splitlines()
        row = None
        for i, line in enumerate(lines):
            if line.strip() == "Instance's subtree :":
                for j in range(i + 1, min(i + 4, len(lines))):
                    if lines[j].split()[:1] == ["SCORE"]:
                        row = _values_after_header(lines, j)
                        break
                break
        if row is None:
            raise ValueError(f"missing or unparseable instance subtree: {name}")
        row["name"] = name
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
    out_path.unlink(missing_ok=True)
    dashboard = cov_dir / "dashboard.txt"
    if not dashboard.is_file():
        sys.exit(
            f"parse_coverage: missing {dashboard}. urg merge did not produce a text report "
            f"(check VCS_COV and urg). NOT emitting structural-coverage.json "
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
    modinfo = cov_dir / "modinfo.txt"
    if not modinfo.is_file():
        sys.exit(f"parse_coverage: missing {modinfo}; no instance coverage to judge")
    mtext = modinfo.read_text(encoding="utf-8", errors="strict")
    per_instance = parse_instances(mtext)
    if not per_instance:
        sys.exit(f"parse_coverage: no instance subtrees in {modinfo}")
    uncovered = parse_uncovered(mtext)
    data = {
        "aggregate": agg,
        "per_instance": per_instance,
        "uncovered": uncovered,
        "source": str(modinfo),
        "urg_version": _urg_version(dtext),
    }
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(
        f"parse_coverage: wrote {out_path} "
        f"(line={agg.get('line')} cond={agg.get('cond')} fsm={agg.get('fsm')} toggle={agg.get('toggle')}"
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
        help="urg report dir (contains dashboard.txt and modinfo.txt)",
    )
    p.add_argument("--out", required=True, help="output structural-coverage.json path")
    args = p.parse_args()
    return build(Path(args.cov_dir).resolve(), Path(args.out).resolve())


if __name__ == "__main__":
    sys.exit(main())
