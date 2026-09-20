"""Read area and precise setup timing, check QOR consistency and judge requirements.

The native timing report supplies signed slack; QOR's rounded summary supplies
violation information, not a replacement measurement. Invalid or missing reports
produce no numerical verdict.
"""

from __future__ import annotations

import datetime
import json
import math
import re
import sys
from pathlib import Path

from synthesis import requirements

# ── Anchors (grounded, DC L-2016.03-SP1) ─────────────────────────────────────
# area.rpt: "Total cell area:                 65018.219263" (NOT "Total area: undefined").
_AREA_RE = re.compile(r"^\s*Total cell area\s*:\s*([0-9.]+)", re.M)
_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_SLACK_RE = re.compile(
    r"^\s*slack\s*\((MET|VIOLATED)[^)]*\)\s*(" + _NUMBER + r")\s*$", re.M
)
_TIME_UNIT_RE = re.compile(r"^\s*Time_unit\s*:\s*(" + _NUMBER + r")\s+Second\b", re.M)
# qor.rpt design summary (setup): "Design  WNS: 0.00  TNS: 0.00  Number of Violating Paths: 0".
# The hold line is "Design (Hold)  WNS: ..." — `Design\s+WNS:` matches the setup line only.
_SETUP_VIOLATIONS_RE = re.compile(
    r"Design\s+WNS:\s*"
    + _NUMBER
    + r"\s+TNS:\s*"
    + _NUMBER
    + r"\s+Number of Violating Paths:\s*(\d+)",
    re.I,
)


def parse_area_um2(text: str) -> float | None:
    """Total cell area in um^2, or None when the anchor is absent."""
    m = _AREA_RE.search(text)
    return float(m.group(1)) if m else None


def parse_worst_slack_ns(text: str) -> float | None:
    """Minimum signed slack in the native setup timing report."""
    unit = _TIME_UNIT_RE.search(text)
    if unit is None:
        return None
    ns_per_unit = float(unit.group(1)) / 1e-9
    if not math.isfinite(ns_per_unit) or ns_per_unit <= 0:
        return None
    values = []
    for marker, token in _SLACK_RE.findall(text):
        value = float(token)
        if (
            not math.isfinite(value)
            or (marker == "MET" and value < 0)
            or (marker == "VIOLATED" and value >= 0)
        ):
            return None
        values.append(value * ns_per_unit)
    return min(values) if values else None


def parse_setup_violations(text: str) -> int | None:
    """Setup violation count from the design summary, excluding the hold summary."""
    match = _SETUP_VIOLATIONS_RE.search(text)
    return int(match.group(1)) if match else None


def run(reports_dir, target_rows) -> tuple[int, dict | None]:
    """Parse + judge every row with a target. Returns (rc, payload); payload is None on any
    non-zero rc."""
    reports_dir = Path(reports_dir)

    area_rpt = reports_dir / "area.rpt"
    qor_rpt = reports_dir / "qor.rpt"
    timing_rpt = reports_dir / "timing_setup.rpt"
    for rpt in (area_rpt, qor_rpt, timing_rpt):
        if not rpt.is_file():
            print(
                f"[synthesis finalize] FAIL=missing required report not found: {rpt}",
                file=sys.stderr,
            )
            return 1, None

    area = parse_area_um2(area_rpt.read_text(errors="replace"))
    if area is None:
        print(
            f"[synthesis finalize] FAIL=unparseable no 'Total cell area' line in {area_rpt}",
            file=sys.stderr,
        )
        return 3, None

    worst = parse_worst_slack_ns(timing_rpt.read_text(errors="replace"))
    if worst is None:
        print(
            f"[synthesis finalize] FAIL=unparseable no usable precise setup slack or time unit in {timing_rpt}",
            file=sys.stderr,
        )
        return 3, None
    violations = parse_setup_violations(qor_rpt.read_text(errors="replace"))
    if violations is None:
        print(
            f"[synthesis finalize] FAIL=unparseable no setup summary in {qor_rpt}",
            file=sys.stderr,
        )
        return 3, None
    if (worst < 0) != (violations > 0):
        print(
            f"[synthesis finalize] FAIL=unparseable setup slack {worst} contradicts "
            f"QOR's {violations} violating paths: {qor_rpt}",
            file=sys.stderr,
        )
        return 3, None

    # The measurements this stage can make, each carrying the sentence that says what it is.
    # A verdict is built from one of these, so a dim with no measurement behind it is a named
    # refusal rather than a KeyError, and the verdict travels with what it measured.
    measurements = [
        {"dim": "area_um2", "value": area, "source": "area.rpt Total cell area"},
        {
            "dim": "timing_slack_ns",
            "value": worst,
            "source": "timing_setup.rpt minimum reported setup slack (ns)",
        },
    ]
    by_dim = {m["dim"]: m for m in measurements}

    # Judge — one entry per targeted row, compared with the engineer's own operator.
    judged = []
    for r in target_rows:
        dim = r["target"]["dim"]
        m = by_dim.get(dim)
        if m is None:
            raise ValueError(
                f"{r['id']} is judged by synthesis with target dim {dim!r}, which this stage "
                f"does not measure (it measures {sorted(by_dim)}) — the row names the wrong "
                f"judge, or the dim is wrong"
            )
        judged.append(
            {
                "id": r["id"],
                "met": requirements.met(m["value"], r["target"]),
                "actual": m["value"],
                "measured": m["source"],
            }
        )

    payload = {
        # What this run read, returned to the caller; the envelope carries only the verdicts,
        # each naming the measurement it came from.
        "measurements": measurements,
        "requirements": judged,
    }
    return 0, payload


# ── finalize: assemble the result.json ───────────────────────────────────────
STAGE = "synthesis"
_FAIL_REASON = {
    "missing": "synthesis report missing",
    "unparseable": "synthesis report unparseable",
}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(*, status, stage_specific, artifacts) -> dict:
    return {
        "stage": STAGE,
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
        f"[synthesis finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def build_result(
    workdir,
    rows,
    declared,
    fix_owner=None,
    fail_reason=None,
) -> int:
    """Assemble the synthesis result.json. Reuses run() for the targeted rows (in-process),
    merges the caller's verdicts on the rest, then derives the header + artifacts + writes
    the envelope. Returns 0 (result.json written, pass or fail). A raise -> finalize()
    exit 2 (BLOCKED) — including a row judged by this stage that nobody judged.

    Three things this verb cannot derive, so the caller states them:

    declared — the verdict on each row with no target: a bound in a unit DC does not
    report, a rule the reports show but no number compares.

    fix_owner — which rule must act. The reports say what missed and by how much;
    whether that means the RTL is wrong or the requirement is malformed is read off the
    rows themselves.

    fail_reason — the cause of a run that produced no gradeable reports, or died after
    writing them. Supplying it IS the declaration of failure: it wins over the gate,
    because the agent watched dc_shell and this verb can only read what landed on disk."""
    workdir = Path(workdir)
    reports = workdir / "reports"

    if fail_reason is not None:
        ss = {"fail_reason": fail_reason}
        if fix_owner:
            ss["fix_owner"] = fix_owner
        _write_result(
            workdir,
            _envelope(
                status="fail",
                stage_specific=ss,
                artifacts=enumerate_artifacts(workdir),
            ),
        )
        return 0

    rc, actual = run(
        reports, [r for r in rows if "target" in r]
    )  # reuse the gate verbatim
    if rc != 0:
        token = (
            "missing" if rc == 1 else "unparseable"
        )  # run(): 1=missing, 3=unparseable
        ss = {"fail_reason": _FAIL_REASON[token]}
        if fix_owner:
            ss["fix_owner"] = fix_owner
        _write_result(
            workdir,
            _envelope(
                status="fail",
                stage_specific=ss,
                artifacts=enumerate_artifacts(workdir),
            ),
        )
        return 0

    judged = requirements.merge(rows, actual["requirements"], declared)
    unmet = requirements.unmet(judged)
    status = "fail" if unmet else "pass"
    area_text = (reports / "area.rpt").read_text(errors="replace")
    ss = {
        "tool": parse_tool(area_text),
        "requirements": judged,
    }
    missing = _missing_netlist(workdir)
    if missing:
        # A report set that grades clean says nothing about whether dc_shell's write
        # step landed: dc_run.tcl reports before change_names/write, and none of the
        # three writes is return-checked, so a failed write leaves a full reports/ and
        # no netlist. Promoting that as a pass publishes a synthesis the two downstream
        # rules declare as their input and cannot find.
        status = "fail"
        ss["fail_reason"] = f"netlist incomplete: required {', '.join(missing)}"
    elif status == "fail":
        ss["fail_reason"] = f"requirement(s) not met: {', '.join(unmet)}"
    if status == "fail" and fix_owner:
        ss["fix_owner"] = fix_owner
    _write_result(
        workdir,
        _envelope(
            status=status,
            stage_specific=ss,
            artifacts=enumerate_artifacts(workdir),
        ),
    )
    return 0


def _missing_netlist(workdir: Path) -> list[str]:
    """A synthesis delivers one nonempty netlist with its matching SDC and SDF."""
    netlists = list(workdir.glob("out/*_syn.v"))
    if len(netlists) != 1:
        return ["exactly one out/*_syn.v"]
    return [
        str(p.relative_to(workdir))
        for p in (netlists[0].with_suffix(ext) for ext in (".v", ".sdc", ".sdf"))
        if not p.is_file() or not p.stat().st_size
    ]


_VERSION_RE = re.compile(r"^\s*Version:\s*(\S+)", re.M)


def parse_tool(area_text: str) -> str:
    """The DC version off the report header. The kernel's reap-time identity record
    covers the library environment variables and no tool version, and this stage's
    reports come from dc_shell; record which compiler produced them."""
    m = _VERSION_RE.search(area_text)
    return f"Design Compiler {m.group(1)}" if m else "Design Compiler unknown"


def enumerate_artifacts(workdir) -> list[dict]:
    """Publish setup, authored helpers and completed products; omit private scratch."""
    workdir = Path(workdir)
    excluded = {
        "result.json",
        "result.json.tmp",
        "dispatch.json",
        "runs",
        ".pending",
        "work",
    }
    return [
        {"path": p.name} for p in sorted(workdir.iterdir()) if p.name not in excluded
    ]


def finalize(
    workdir,
    rows,
    declared,
    fix_owner=None,
    fail_reason=None,
) -> int:
    """Parse DC reports, judge the rows synthesis establishes, write result.json. exit 0 =
    written (pass or fail); exit 2 = BLOCKED (an empty --fail-reason, a row nobody judged, or
    any internal raise) — never conflated with status=fail."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if fail_reason is not None:
        if not fail_reason.strip():
            print(
                "[synthesis finalize] BLOCKED: --fail-reason must be a non-empty "
                "one-line cause",
                file=sys.stderr,
            )
            return 2
    try:
        return build_result(workdir, rows, declared, fix_owner, fail_reason)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[synthesis finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
