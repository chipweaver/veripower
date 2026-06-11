#!/usr/bin/env python3
"""collect_report.py — locate, render, and parse a SpyGlass lint/CDC report.

Single owner of the lint-cdc "report" step. Given {lint|cdc}, run() — relative to
the run workdir `root` — does:
  1. remove any prior {kind}-report.txt / {kind}-violations.json (write-fresh-or-nothing),
  2. locate the source moresimple.rpt under root/spyglass_work/,
  3. parse the header message totals (generated / waived / reported / overlimit),
  4. parse the per-message rows,
  5. reconcile parsed rows against the header totals (the completeness guarantee),
  6. on success write both {kind}-report.txt and {kind}-violations.json.

Exit codes (each non-zero also prints a greppable FAIL=<token> on stderr):
  0  located + parsed + reconciled (incl. a legitimate 0-message clean run)
  1  no source report found                              -> FAIL=missing
  3  no 'Number of Reported Messages' header, a bracket
     row that won't parse, or an unrecognized severity   -> FAIL=unparseable
  3  bracket rows != reported, generated != waived +
     reported, or overlimit > 0                          -> FAIL=count_mismatch
  2  usage error

FORMAT — grounded against real SpyGlass vL-2016.06 moresimple.rpt (sdc_controller
eval corpus, 20 reports). moresimple.rpt is a sectioned report; each reported
message is one
    [ID]  Rule  (Alias may be empty or multi-word)  Severity  File  Line  Wt  Message
row, and the header comment block carries the message totals. There is no
per-severity summary, so per-severity counts are derived from rows and the
completeness guarantee is the header total: count of '[ID]' rows == 'Number of
Reported Messages', plus the generated == waived + reported identity. On any format
surprise (a bracket row that won't parse, an unknown severity, a count that does
not reconcile) the parser fails loud (exit 3) rather than miscounting.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ── Row + header format (grounded) ──────────────────────────────────────────
# One reported message per line. Anchored on [ID], the first token (Rule), and the
# trailing File Line(int) Wt(int) Message; the field between Rule and File is
# "alias... severity" (severity = its last whitespace token, so empty and multi-word
# aliases both parse).
_ROW = re.compile(
    r"^\[(\w+)\][ \t]+(\S+)[ \t]+(.*?)[ \t]+(\S+)[ \t]+(\d+)[ \t]+(\d+)[ \t]+(.*\S)[ \t]*$",
    re.M,
)
_BRACKET = re.compile(r"^\[\w+\]", re.M)

_HDR_GENERATED = re.compile(r"Number of Generated Messages[ \t]*:[ \t]*(\d+)", re.I)
_HDR_WAIVED = re.compile(r"Number of Waived Messages[ \t]*:[ \t]*(\d+)", re.I)
_HDR_REPORTED = re.compile(r"Number of Reported Messages[ \t]*:[ \t]*(\d+)", re.I)
_HDR_OVERLIMIT = re.compile(r"Number of Overlimit Messages[ \t]*:[ \t]*(\d+)", re.I)

# ── Source-report location (unchanged) ──────────────────────────────────────
_LINT_CANDIDATES = [
    ("/lint/lint_rtl/", "moresimple.rpt"),
    ("_lint_lint_rtl", "moresimple.rpt"),
    ("/lint/lint_rtl/", "elab_summary.rpt"),
]
_CDC_CANDIDATES = [
    ("/cdc/cdc_verify_struct/", "moresimple.rpt"),
    ("/cdc/cdc_verify_struct/", "cdc_violations.rpt"),
    ("/cdc/cdc_verify_struct/", "cdc_setup.rpt"),
    ("_cdc_cdc_verify_struct", "moresimple.rpt"),
    ("/cdc/cdc_setup_check/", "cdc_setup_check.rpt"),
    ("/cdc/cdc_setup_check/", "moresimple.rpt"),
    ("/cdc/cdc_setup/", "cdc_setup.rpt"),
    ("/cdc/cdc_setup/", "moresimple.rpt"),
]


def locate(kind: str, work: Path) -> Path | None:
    """First existing report in priority order, or None."""
    candidates = _LINT_CANDIDATES if kind == "lint" else _CDC_CANDIDATES
    for frag, name in candidates:
        for p in sorted(work.rglob(name)):
            if frag in p.as_posix():
                return p
    return None


# ── Parsing ──────────────────────────────────────────────────────────────
def _sev(token: str) -> str | None:
    """Map a SpyGlass severity token to the schema enum, or None if unrecognized.

    Substring-based, so compound tokens classify correctly (SynthesisError -> error,
    a hypothetical SynthesisWarning -> warning). An unrecognized token returns None
    and run() fails loud rather than guessing.
    """
    t = token.lower()
    if "fatal" in t or "error" in t:
        return "error"
    if "warning" in t:
        return "warning"
    if "info" in t:
        return "info"
    return None


def parse_header(text: str) -> dict | None:
    """Header message totals, or None when the 'Reported' anchor is absent.

    Returns {generated, waived, reported, overlimit}; generated/waived/overlimit are
    None when their line is absent (reported is the required structural anchor ->
    its absence means an unrecognized report, caller exits 3 FAIL=unparseable).
    """
    m_rep = _HDR_REPORTED.search(text)
    if not m_rep:
        return None

    def g(rx):
        m = rx.search(text)
        return int(m.group(1)) if m else None

    return {
        "generated": g(_HDR_GENERATED),
        "waived": g(_HDR_WAIVED),
        "reported": int(m_rep.group(1)),
        "overlimit": g(_HDR_OVERLIMIT),
    }


def parse_rows(text: str) -> list[dict]:
    """Reported message rows as dicts: native_id / rule / sev_token / file / line / message.

    Severity is the last whitespace token of the alias+severity field (group 3), so
    an empty or multi-word alias both parse correctly.
    """
    out: list[dict] = []
    for native_id, rule, alias_sev, fname, line, _wt, msg in _ROW.findall(text):
        toks = alias_sev.split()
        out.append(
            {
                "native_id": native_id,
                "rule": rule,
                "sev_token": toks[-1] if toks else "",
                "file": fname,
                "line": int(line),
                "message": msg,
            }
        )
    return out


def count_raw(rows: list[dict]) -> dict | None:
    """Per-severity tally from rows; None if any row's severity is unrecognized."""
    c = {"error": 0, "warning": 0, "info": 0}
    for r in rows:
        s = _sev(r["sev_token"])
        if s is None:
            return None
        c[s] += 1
    return c


def build_violations(rows: list[dict]) -> list[dict]:
    """One entry per reported row (all severities); synthesize a stable id,
    ordinal-disambiguating collisions, and keep the native [ID] for traceability.

    The synthesized id (<rule>:<file>:<line>) is the cross-run-stable rework key;
    native_id is the run-local SpyGlass [ID] for cross-referencing the source row.
    """
    id_seq: dict = {}
    out: list[dict] = []
    for r in rows:
        base = f"{r['rule']}:{r['file']}:{r['line']}"
        n = id_seq.get(base, 0) + 1
        id_seq[base] = n
        out.append(
            {
                "id": base if n == 1 else f"{base}#{n}",
                "native_id": r["native_id"],
                "rule": r["rule"],
                "severity": _sev(r["sev_token"]),
                "file": r["file"],
                "line": r["line"],
                "message": r["message"],
            }
        )
    return out


# ── Human-report header (unchanged) ──────────────────────────────────────────
def read_top(root: Path) -> str:
    v = os.environ.get("TOP")
    if v:
        return v
    env = root / "env.sh"
    if env.exists():
        txt = env.read_text(errors="replace")
        m = re.search(r'TOP="?\$\{TOP:-([A-Za-z_][A-Za-z0-9_]*)\}"?', txt)
        if m:
            return m.group(1)
        m = re.search(r'export[ \t]+TOP=["\']?([A-Za-z_][A-Za-z0-9_]*)', txt)
        if m:
            return m.group(1)
    return "UNKNOWN"


def render_human(kind: str, src: Path, top: str, body: str) -> str:
    return (
        f"=== IPD {kind}-report (SpyGlass) ===\n"
        f"date: {datetime.now().isoformat()}\n"
        f"cwd:  {Path.cwd()}\n"
        f"top:  {top}\n\n"
        f"=== source: {src} ===\n"
        f"{body}"
    )


# ── Orchestration ────────────────────────────────────────────────────────
def run(kind: str, root: Path) -> int:
    root = Path(root)
    out_txt = root / f"{kind}-report.txt"
    out_json = root / f"{kind}-violations.json"

    # Write-fresh-or-nothing: clear prior outputs up front.
    for p in (out_txt, out_json):
        if p.exists():
            p.unlink()

    src = locate(kind, root / "spyglass_work")
    if src is None:
        print(
            f"[collect_report] FAIL=missing no {kind} source report found in "
            f"{root / 'spyglass_work'}",
            file=sys.stderr,
        )
        return 1

    text = src.read_text(errors="replace")

    header = parse_header(text)
    if header is None:
        print(
            f"[collect_report] FAIL=unparseable {kind} report has no "
            f"'Number of Reported Messages' header: {src}",
            file=sys.stderr,
        )
        return 3

    rows = parse_rows(text)
    n_bracket = len(_BRACKET.findall(text))
    if len(rows) != n_bracket:
        print(
            f"[collect_report] FAIL=unparseable {kind} report: "
            f"{n_bracket - len(rows)} '[ID]' row(s) did not parse (format drift): {src}",
            file=sys.stderr,
        )
        return 3

    counts = count_raw(rows)
    if counts is None:
        print(
            f"[collect_report] FAIL=unparseable {kind} report: "
            f"unrecognized severity token: {src}",
            file=sys.stderr,
        )
        return 3

    if n_bracket != header["reported"]:
        print(
            f"[collect_report] FAIL=count_mismatch {kind} parsed rows {n_bracket} != "
            f"reported {header['reported']}: {src}",
            file=sys.stderr,
        )
        return 3

    if header["overlimit"]:
        print(
            f"[collect_report] FAIL=count_mismatch {kind} report has "
            f"{header['overlimit']} overlimit-suppressed message(s); raise the per-rule "
            f"limit and re-run: {src}",
            file=sys.stderr,
        )
        return 3

    if (
        header["generated"] is not None
        and header["waived"] is not None
        and header["generated"] != header["waived"] + header["reported"]
    ):
        print(
            f"[collect_report] FAIL=count_mismatch {kind} generated {header['generated']} "
            f"!= waived {header['waived']} + reported {header['reported']}: {src}",
            file=sys.stderr,
        )
        return 3

    violations = build_violations(rows)
    out_txt.write_text(render_human(kind, src, read_top(root), text))
    out_json.write_text(
        json.dumps(
            {
                "kind": kind,
                "source": src.as_posix(),
                "counts": counts,
                "totals": header,
                "violations": violations,
            },
            indent=2,
        )
        + "\n"
    )
    sys.stdout.write(
        f"[collect_report] Written: {out_txt} + {out_json} (source: {src})\n"
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("lint", "cdc"):
        print(
            "[collect_report] ERROR: usage: collect_report.py {lint|cdc}",
            file=sys.stderr,
        )
        return 2
    root = Path(__file__).resolve().parent.parent  # runs/<N>/ (scripts/ -> runs/<N>/)
    return run(argv[1], root)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
