"""Read reported setup/hold results and judge their numerical requirements.

Analysis scope and exceptions are assessed from native reports by the stage owner.
An explicit fail_reason records incomplete or invalid analysis.
"""

from __future__ import annotations

import datetime
import json
import math
import re
import sys
from pathlib import Path

from timing import requirements

SLACK_SIGN_TOLERANCE_NS = 1e-4

# Each report_timing block carries a header line '-delay_type max|min'.
DELAY_MAX_RE = re.compile(r"-delay_type\s+max")
DELAY_MIN_RE = re.compile(r"-delay_type\s+min")
# A path's slack line: 'slack (MET) 2.93' or 'slack (VIOLATED: increase significant digits) 0.00'.
SLACK_RE = re.compile(r"slack\s*\((MET|VIOLATED)[^)]*\)\s*([-+0-9.]+)")
START_RE = re.compile(r"Startpoint:\s*(\S+)")
END_RE = re.compile(r"Endpoint:\s*(\S+)")
COVERAGE_TABLE_RE = re.compile(r"^Type of Check\s+Total", re.M)
TIME_UNIT_RE = re.compile(
    r"^\s*Time_unit\s*:\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s+Second\b",
    re.M,
)


class ParseError(Exception):
    """Raised on a format surprise; caller maps it to exit 3 (FAIL=unparseable)."""


def timing_section(text: str, kind: str) -> str:
    """Return the text of the `-delay max` or `-delay min` report section.

    Setup = from the first -delay_type max header to the first -delay_type min header.
    Hold  = from the first -delay_type min header to end. Raise if the header is absent.
    """
    mmax = DELAY_MAX_RE.search(text)
    mmin = DELAY_MIN_RE.search(text)
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
    section = timing_section(text, kind)
    unit = TIME_UNIT_RE.search(text)
    if unit is None:
        raise ParseError("no report_units time unit in the report")
    ns_per_unit = float(unit.group(1)) / 1e-9
    if not math.isfinite(ns_per_unit) or ns_per_unit <= 0:
        raise ParseError("invalid report_units time unit")
    paths = []
    # Split into path blocks at each 'Startpoint:'; the leading chunk is the header.
    for block in re.split(r"(?=Startpoint:)", section):
        m = SLACK_RE.search(block)
        if not m:
            continue
        marker, raw = m.group(1), float(m.group(2)) * ns_per_unit
        # A marker that disagrees with its own number means the line is not the shape
        # this parser was grounded on; fail loud rather than trust either half.
        if marker == "MET" and raw < -SLACK_SIGN_TOLERANCE_NS:
            raise ParseError(f"MET marker with negative slack {raw}")
        if marker == "VIOLATED" and raw > SLACK_SIGN_TOLERANCE_NS:
            raise ParseError(f"VIOLATED marker with positive slack {raw}")
        s = START_RE.search(block)
        e = END_RE.search(block)
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


def run(report_path) -> tuple[int, dict | None]:
    """Classify + judge. Returns (rc, payload); payload is None on any non-zero rc."""
    report_path = Path(report_path)

    if not report_path.is_file():
        print(
            f"[timing finalize] FAIL=missing report not found: {report_path}",
            file=sys.stderr,
        )
        return 1, None

    text = report_path.read_text(errors="replace")
    try:
        if not COVERAGE_TABLE_RE.search(text):
            raise ParseError("no report_analysis_coverage table in the report")
        setup = parse_direction(text, "max")
        hold = parse_direction(text, "min")
    except ParseError as exc:
        print(
            f"[timing finalize] FAIL=unparseable {exc}: {report_path}",
            file=sys.stderr,
        )
        return 3, None

    payload = {
        "verdict": "pass" if setup["met"] and hold["met"] else "fail",
        "timing": {"setup": setup, "hold": hold},
    }
    return 0, payload


STAGE = "timing-analysis"
FAIL_REASON = {
    "missing": "timing-report.txt missing",
    "unparseable": "timing-report.txt unparseable",
}

VERSION_RE = re.compile(r"^\s*Version:\s*(\S+)", re.M)


def enumerate_artifacts(workdir: Path) -> list:
    """Publish setup, authored helpers and completed products; omit private scratch."""
    workdir = Path(workdir)
    excluded = {
        "result.json",
        "result.json.tmp",
        "dispatch.json",
        "runs",
        ".pending",
    }
    return [
        {"path": p.name} for p in sorted(workdir.iterdir()) if p.name not in excluded
    ]


def finalize(workdir, rows, declared, fix_owner=None, fail_reason=None) -> int:
    """Assess the stage and write its result. Input or I/O errors leave no current result."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if fail_reason is not None:
        if not fail_reason.strip():
            print(
                "[timing finalize] BLOCKED: --fail-reason must be a non-empty one-line cause",
                file=sys.stderr,
            )
            return 2

    def _write_result(*, status, stage_specific, artifacts):
        result = {
            "stage": STAGE,
            "produced_at": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "status": status,
            "artifacts": artifacts,
            "stage_specific": stage_specific,
        }
        result_path = Path(workdir) / "result.json"
        temporary_path = result_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(result, indent=2) + "\n")
        temporary_path.replace(result_path)
        print(f"[timing finalize] Written: {result_path} (status={status})")
        return 0

    try:
        workdir = Path(workdir)
        report = workdir / "timing-report.txt"
        if fail_reason is not None:
            stage_specific = {"fail_reason": fail_reason}
            if fix_owner:
                stage_specific["fix_owner"] = fix_owner
            return _write_result(
                status="fail",
                stage_specific=stage_specific,
                artifacts=enumerate_artifacts(workdir),
            )
        exit_code, actual = run(report)
        if exit_code != 0:
            token = "missing" if exit_code == 1 else "unparseable"
            stage_specific = {"fail_reason": FAIL_REASON[token]}
            if fix_owner:
                stage_specific["fix_owner"] = fix_owner
            return _write_result(
                status="fail",
                stage_specific=stage_specific,
                artifacts=enumerate_artifacts(workdir),
            )
        status = "pass" if actual["verdict"] == "pass" else "fail"
        report_text = report.read_text(errors="replace")
        version_match = VERSION_RE.search(report_text)
        tool = (
            f"PrimeTime {version_match.group(1)}"
            if version_match
            else "PrimeTime unknown"
        )
        judged = requirements.merge(
            rows, requirements.compare(rows, actual["timing"]), declared
        )
        unmet = [entry["id"] for entry in judged if not entry["met"]]
        stage_specific = {
            "tool": tool,
            "timing": actual["timing"],
            "requirements": judged,
        }
        if status == "fail":
            stage_specific["fail_reason"] = "setup/hold timing not met"
        elif unmet:
            status = "fail"
            stage_specific["fail_reason"] = (
                f"requirement(s) not met: {', '.join(unmet)}"
            )
        if status == "fail" and fix_owner:
            stage_specific["fix_owner"] = fix_owner
        return _write_result(
            status=status,
            stage_specific=stage_specific,
            artifacts=enumerate_artifacts(workdir),
        )
    except (OSError, ValueError) as exc:
        print(f"[timing finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
