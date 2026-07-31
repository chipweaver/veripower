"""timing.result — classify a PrimeTime STA report (marker-keyed) and judge the gate.

Single owner of timing-analysis's self-check. Reads the bare-`report_timing`
deliverable (timing-report.txt: a `-delay max` section, a `-delay min` section,
then check_timing and the coverage table), classifies each direction on the
(MET)/(VIOLATED) MARKER (never the displayed number — a sub-rounding violation prints
'0.00'), and records the worst slack + worst path per direction.

A pass needs both: setup MET and hold MET, AND every output bit actually timed. The
markers grade the paths PT analyzed and say nothing about the ones an incomplete SDC
kept it from analyzing at all, so the two are separate questions and a MET pair alone
is not an answer to the second.

The boundary is measured on OUTPUTS only. check_timing's unconstrained-endpoint count
looks like the more direct measure and is not usable as one: reset ports carry no input
delay by construction (specification's derive-constraints gives IO delay to data ports
alone), so every async-reset flop lands in that count on a correctly constrained design
— measured across eight synthesized designs it read 0 to 4242 with a complete SDC, and
on two of them it was IDENTICAL with an incomplete one. Output bits carry no such
exemption: every output port is a data port, so the count PT should have timed is
determined, and out_setup's Total is what it did.

Exit codes (each non-zero also prints a greppable FAIL=<token> on stderr):
  0  parsed + judged (incl. a legitimate verdict="fail")
  1  report file absent                                   -> FAIL=missing
  3  a delay section has no parseable slack line, a marker contradicts its sign
     (MET with slack < -eps / VIOLATED with slack > +eps), or a check_timing check
     never ran                                            -> FAIL=unparseable
  2  usage error                                          -> ERROR: usage

The judged payload is returned in-process to build_result rather than through a
sidecar: result.json already carries every field of it.

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
# Boundary coverage: the count run_sta.tcl emits, against report_analysis_coverage's
# out_setup row. The row is absent entirely when the run timed no output at all.
_OUTPUT_BITS_RE = re.compile(r"^Boundary output bits:\s*(\d+)", re.M)
_OUT_SETUP_RE = re.compile(r"^out_setup\s+(\d+)", re.M)
_COVERAGE_TABLE_RE = re.compile(r"^Type of Check\s+Total", re.M)


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
        # A marker that disagrees with its own number means the line is not the shape
        # this parser was grounded on; fail loud rather than trust either half.
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
    """How much of the design boundary this run actually timed.

    `output_bits` is what run_sta.tcl counted off the linked design; `output_bits_timed`
    is report_analysis_coverage's out_setup Total, which counts one check per output bit
    that carries an output delay. The out_setup row is absent altogether from a run that
    timed no output, so its absence reads as zero — but only once the table itself is
    known to be present, since a truncated report would otherwise read as a design with
    no outputs at all. Raises ParseError when either anchor is missing.
    """
    m = _OUTPUT_BITS_RE.search(text)
    if m is None:
        raise ParseError("no 'Boundary output bits' line in the report")
    if not _COVERAGE_TABLE_RE.search(text):
        raise ParseError("no report_analysis_coverage table in the report")
    timed = _OUT_SETUP_RE.search(text)
    return {
        "output_bits": int(m.group(1)),
        "output_bits_timed": int(timed.group(1)) if timed else 0,
    }


def uncovered(coverage: dict) -> str | None:
    """The phrase for a boundary the run did not time in full; None when it did."""
    bits, timed = coverage["output_bits"], coverage["output_bits_timed"]
    if timed >= bits:
        return None
    return f"timed {timed} of {bits} output bits"


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
        setup = parse_direction(text, "max")
        hold = parse_direction(text, "min")
        coverage = parse_coverage(text)
    except ParseError as exc:
        print(
            f"[timing finalize] FAIL=unparseable {exc}: {report_path}",
            file=sys.stderr,
        )
        return 3, None

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
    return 0, payload


STAGE = "timing-analysis"
_FAIL_REASON = {
    "missing": "timing-report.txt missing",
    "unparseable": "timing-report.txt unparseable",
}

_VERSION_RE = re.compile(r"^\s*Version:\s*(\S+)", re.M)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts) -> dict:
    return {
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
    tmp.replace(workdir / "result.json")  # atomic: never observed half-written
    sys.stdout.write(
        f"[timing finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def parse_tool(report_text: str) -> str:
    """The PrimeTime version off the report header. The kernel's reap-time identity
    record covers the library environment variables and no tool version, and this
    stage's oracle IS pt_shell, so nothing else names which engine produced the proof."""
    m = _VERSION_RE.search(report_text)
    return f"PrimeTime {m.group(1)}" if m else "PrimeTime unknown"


def enumerate_artifacts(workdir: Path) -> list:
    workdir = Path(workdir)
    candidates = [
        "run_sta.tcl",
        "config.tcl",
        "timing-report.txt",
    ]
    # envelope.schema forbids listing result.json itself; excluded by construction.
    return [{"path": p} for p in candidates if (workdir / p).is_file()]


def build_result(
    workdir, module, fix_owner=None, fail_reason=None, failure_kind=None
) -> int:
    """Assemble the lean timing-analysis result.json. Reuses run() for the timing gate
    (in-process), then derives the header + artifacts + writes the envelope.
    Returns 0 (result.json written, pass or fail). A raise -> finalize() exit 2 (BLOCKED).

    Three things this verb cannot derive, so the caller states them:

    fix_owner — which rule must act. The report says what failed; whose artifact is at
    fault is the caller's reading.

    fail_reason — the cause of a run that produced no gradeable report. Supplying it IS
    the declaration of failure: it wins over the gate, because the agent watched pt_shell
    and this verb can only read what landed on disk.

    failure_kind — infra or tooling for such a declaration. An absent report looks
    identical whether PrimeTime never started (no license) or died at link_design, and
    only the caller saw which."""
    workdir = Path(workdir)
    report = workdir / "timing-report.txt"

    if fail_reason is not None:
        ss = {"fail_reason": fail_reason, "failure_kind": failure_kind}
        if fix_owner:
            ss["fix_owner"] = fix_owner
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

    rc, actual = run(report)  # reuse the gate verbatim
    if rc != 0:
        token = (
            "missing" if rc == 1 else "unparseable"
        )  # run(): 1=missing, 3=unparseable
        ss = {
            "fail_reason": _FAIL_REASON[token],
            "failure_kind": "tooling",
        }
        if fix_owner:
            ss["fix_owner"] = fix_owner
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

    status = "pass" if actual["verdict"] == "pass" else "fail"
    report_text = report.read_text(errors="replace")
    ss = {
        "tool": parse_tool(report_text),
        "timing": actual["timing"],
        "violations": actual["violations"],
    }
    left_out = uncovered(actual["timing"]["coverage"])
    if left_out:
        # A pair of MET markers says nothing about how much of the boundary was timed:
        # PT reports MET on the paths it analyzed whether the SDC reached two output
        # bits or two hundred. Promoting that as a pass publishes a tool-grade proof
        # over a boundary the STA never covered, and this stage exists to be the
        # independent check that catches it.
        status = "fail"
        ss["failure_kind"] = "tooling"
        ss["fail_reason"] = f"STA did not cover the boundary: {left_out}"
    elif status == "fail":
        ss["failure_kind"] = "ppa"
        ss["fail_reason"] = "setup/hold timing not met"
    if status == "fail" and fix_owner:
        ss["fix_owner"] = fix_owner
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


def finalize(
    workdir, module, fix_owner=None, fail_reason=None, failure_kind=None
) -> int:
    """Parse the PT report, judge the timing gate, write the lean result.json.
    exit 0 = written (pass or fail); exit 2 = BLOCKED (an empty --fail-reason, one
    without a --failure-kind, or any internal raise) — never conflated with
    status=fail."""
    if fail_reason is not None:
        if not fail_reason.strip():
            print(
                "[timing finalize] BLOCKED: --fail-reason must be a non-empty "
                "one-line cause",
                file=sys.stderr,
            )
            return 2
        if not failure_kind:
            print(
                "[timing finalize] BLOCKED: --fail-reason needs --failure-kind "
                "{infra,tooling}",
                file=sys.stderr,
            )
            return 2
    try:
        return build_result(workdir, module, fix_owner, fail_reason, failure_kind)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[timing finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
