"""timing.result — classify a PrimeTime STA report (marker-keyed) and judge the gate.

Single owner of timing-analysis's self-check. Reads the bare-`report_timing`
deliverable (timing-report.txt: a `-delay max` section, a `-delay min` section,
then check_timing), classifies each direction on the (MET)/(VIOLATED) MARKER
(never the displayed number — a sub-rounding violation prints '0.00'), records the
worst slack + worst path per direction and the two check_timing coverage counts,
and judges pass = setup MET and hold MET. Coverage is recorded, never gated.

Exit codes (each non-zero also prints a greppable FAIL=<token> on stderr):
  0  parsed + judged (incl. a legitimate verdict="fail")
  1  report file absent                                   -> FAIL=missing
  3  a delay section has no parseable slack line, OR a marker contradicts its sign
     (MET with slack < -eps / VIOLATED with slack > +eps)  -> FAIL=unparseable
  2  usage error                                          -> ERROR: usage

`timing-actual.json` is written ONLY on exit 0.

FORMAT — grounded against pt2016 (M-2016.12-SP1) sdc_controller reports. Bare
`report_timing -delay max|min` prints the worst path per group; each block ends in
a `slack (MET)` / `slack (VIOLATED...)` line. check_timing prints `There are N
endpoints which are not constrained for maximum delay` and `There are N register
clock pins with no clock`. The number is recorded with
report_default_significant_digits=4 (set in run_sta.tcl); the marker stays
authoritative for met/violated. On any parse surprise the parser fails loud
(exit 3) rather than emitting a silent pass.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

_EPS = 1e-4

# Each report_timing block carries a header line '-delay_type max|min'.
_DELAY_MAX_RE = re.compile(r"-delay_type\s+max")
_DELAY_MIN_RE = re.compile(r"-delay_type\s+min")
# A path's slack line: 'slack (MET) 2.93' or 'slack (VIOLATED: increase significant digits) 0.00'.
_SLACK_RE = re.compile(r"slack\s*\((MET|VIOLATED)[^)]*\)\s*([-+0-9.]+)")
_START_RE = re.compile(r"Startpoint:\s*(\S+)")
_END_RE = re.compile(r"Endpoint:\s*(\S+)")
# check_timing coverage lines.
_UNCONSTRAINED_RE = re.compile(
    r"There are (\d+) endpoints which are not constrained for maximum delay"
)
_NOCLOCK_RE = re.compile(r"There are (\d+) register clock pins with no clock")


class ParseError(Exception):
    """Raised on a format surprise; caller maps it to exit 3 (FAIL=unparseable)."""


def _section(text: str, kind: str) -> str:
    """Return the text of the `-delay max` or `-delay min` report section.

    Setup = from the first -delay_type max header to the first -delay_type min header.
    Hold  = from the first -delay_type min header to end. Raise if the header is absent.
    """
    mmax = _DELAY_MAX_RE.search(text)
    mmin = _DELAY_MIN_RE.search(text)
    if kind == "max":
        if mmax is None:
            raise ParseError("no '-delay_type max' section header")
        end = mmin.start() if (mmin and mmin.start() > mmax.start()) else len(text)
        return text[mmax.start() : end]
    if mmin is None:
        raise ParseError("no '-delay_type min' section header")
    return text[mmin.start() :]


def parse_direction(text: str, kind: str) -> dict:
    """{met, worst_slack_ns, worst_path} for `max` (setup) or `min` (hold).

    Classifies on the marker; records the worst (min-slack) path. Raises ParseError
    when the section has no slack line or a marker contradicts its sign.
    """
    section = _section(text, kind)
    paths = []
    # Split into path blocks at each 'Startpoint:'; the leading chunk is the header.
    for block in re.split(r"(?=Startpoint:)", section):
        m = _SLACK_RE.search(block)
        if not m:
            continue
        marker, raw = m.group(1), float(m.group(2))
        # Marker-vs-sign cross-check (fail-loud, mirrors synthesis WNS xcheck).
        if marker == "MET" and raw < -_EPS:
            raise ParseError(f"MET marker with negative slack {raw}")
        if marker == "VIOLATED" and raw > _EPS:
            raise ParseError(f"VIOLATED marker with positive slack {raw}")
        s = _START_RE.search(block)
        e = _END_RE.search(block)
        paths.append(
            {
                "start": s.group(1) if s else "?",
                "end": e.group(1) if e else "?",
                "marker": marker,
                "slack": raw,
            }
        )
    if not paths:
        raise ParseError(f"no 'slack (...)' line in -delay_type {kind} section")
    worst = min(paths, key=lambda p: p["slack"])
    return {
        "worst_slack_ns": worst["slack"],
        "met": all(p["marker"] == "MET" for p in paths),
        "worst_path": f"{worst['start']} -> {worst['end']}",
    }


def parse_coverage(text: str) -> dict:
    """check_timing coverage counts (default 0 when a line is absent). Recorded, not gated."""
    u = _UNCONSTRAINED_RE.search(text)
    n = _NOCLOCK_RE.search(text)
    return {
        "unconstrained_max_delay_endpoints": int(u.group(1)) if u else 0,
        "register_pins_no_clock": int(n.group(1)) if n else 0,
    }


def run(report_path, out_path) -> int:
    report_path = Path(report_path)
    out_path = Path(out_path)

    # Write-fresh-or-nothing.
    if out_path.exists():
        out_path.unlink()

    if not report_path.is_file():
        print(
            f"[timing finalize] FAIL=missing report not found: {report_path}",
            file=sys.stderr,
        )
        return 1

    text = report_path.read_text(errors="replace")
    try:
        setup = parse_direction(text, "max")
        hold = parse_direction(text, "min")
    except ParseError as exc:
        print(
            f"[timing finalize] FAIL=unparseable {exc}: {report_path}",
            file=sys.stderr,
        )
        return 3

    coverage = parse_coverage(text)

    violations = []
    if not setup["met"]:
        violations.append(
            {
                "dim": "timing_setup",
                "target": 0,
                "actual": setup["worst_slack_ns"],
                "path_id": setup["worst_path"],
            }
        )
    if not hold["met"]:
        violations.append(
            {
                "dim": "timing_hold",
                "target": 0,
                "actual": hold["worst_slack_ns"],
                "path_id": hold["worst_path"],
            }
        )
    verdict = "fail" if violations else "pass"

    payload = {
        "verdict": verdict,
        "timing": {"setup": setup, "hold": hold, "coverage": coverage},
        "violations": violations,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    sys.stdout.write(f"[timing finalize] Written: {out_path} (verdict={verdict})\n")
    return 0


STAGE = "timing-analysis"
_FAIL_REASON = {
    "missing": "timing-report.txt missing",
    "unparseable": "timing-report.txt unparseable",
}

_VERSION_RE = re.compile(r"^\s*Version:\s*(\S+)", re.M)
_LIBDB_RE = re.compile(r"set\s+LIB_DB\s+(\S+)")
# Port-first create_clock (real synthesis SDC): create_clock [get_ports i_clk] -period 10 ...
_CLOCK_RE = re.compile(
    r"create_clock\s+\[get_ports\s+(\S+?)\][^\n]*?-period\s+([0-9.]+)"
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts) -> dict:
    return {
        "schema_version": 1,
        "stage": STAGE,
        "module": module,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": artifacts,
        "stage_specific": stage_specific,
    }


def _write_result(workdir: Path, env: dict) -> None:
    tmp = workdir / "result.json.tmp"
    tmp.write_text(json.dumps(env, indent=2) + "\n")
    tmp.replace(
        workdir / "result.json"
    )  # atomic: never observed half-written
    sys.stdout.write(
        f"[timing finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def parse_tool(report_text: str) -> str:
    m = _VERSION_RE.search(report_text)
    return f"PrimeTime {m.group(1)}" if m else "PrimeTime unknown"


def read_lib_db(workdir: Path):
    cfg = Path(workdir) / "config.tcl"
    if not cfg.is_file():
        return None
    m = _LIBDB_RE.search(cfg.read_text(errors="replace"))
    return m.group(1) if m else None


def parse_clock(workdir: Path, top: str):
    # The STA reads the synthesis SDC; workdir is .../Design/timing-analysis/runs/<N>.
    # parents[0]=runs, [1]=timing-analysis, [2]=Design, [3]=module root
    sdc = Path(workdir).parents[3] / "Design" / "synthesis" / "out" / f"{top}_syn.sdc"
    if not sdc.is_file():
        return None
    m = _CLOCK_RE.search(sdc.read_text(errors="replace"))
    return {"name": m.group(1), "period_ns": float(m.group(2))} if m else None


def enumerate_artifacts(workdir: Path) -> list:
    workdir = Path(workdir)
    candidates = [
        "run_sta.tcl",
        "config.tcl",
        "timing-report.txt",
        "timing-actual.json",
    ]
    # envelope.schema forbids listing result.json itself; excluded by construction.
    return [{"path": p} for p in candidates if (workdir / p).is_file()]


def build_result(workdir, module, top) -> int:
    """Assemble the lean timing-analysis result.json. Reuses run() for the timing gate
    (in-process), then derives the header + artifacts + writes the envelope.
    Returns 0 (result.json written, pass or fail). A raise -> main() exit 2 (BLOCKED)."""
    workdir = Path(workdir)
    report = workdir / "timing-report.txt"
    sidecar = workdir / "timing-actual.json"

    rc = run(report, sidecar)  # reuse the gate verbatim
    if rc != 0:
        token = (
            "missing" if rc == 1 else "unparseable"
        )  # run(): 1=missing, 3=unparseable
        ss = {
            "top_module": top,
            "fail_reason": _FAIL_REASON[token],
            "failure_kind": "tooling",
        }
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=enumerate_artifacts(workdir),
            ),
        )
        return 0

    actual = json.loads(sidecar.read_text())  # the tool's own artifact (in-process)
    status = "pass" if actual["verdict"] == "pass" else "fail"
    report_text = report.read_text(errors="replace")
    ss = {
        "tool": parse_tool(report_text),
        "top_module": top,
        "lib_db": read_lib_db(workdir),
        "clock": parse_clock(workdir, top),
        "timing": actual["timing"],
        "violations": actual["violations"],
    }
    if status == "fail":
        ss["failure_kind"] = "ppa"
        ss["fail_reason"] = "setup/hold timing not met"
    _write_result(
        workdir,
        _envelope(
            module,
            status=status,
            stage_specific=ss,
            artifacts=enumerate_artifacts(workdir),
        ),
    )
    return 0


def finalize(workdir, module, top) -> int:
    """Parse the PT report, judge the timing gate, write the lean result.json.
    exit 0 = written (pass or fail); exit 2 = BLOCKED (any internal raise) — never
    conflated with status=fail. (Owns the policy the deleted main() finalize branch had.)"""
    try:
        return build_result(workdir, module, top)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[timing finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
