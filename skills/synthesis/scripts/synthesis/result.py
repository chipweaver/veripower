"""synthesis.result — extract the two PPA scalars from DC reports and judge the requirements.

Single owner of the synthesis "PPA self-check" step. run() returns (rc, payload); a
non-zero rc yields no payload, so a parse failure can never fold a half-read number
into a verdict. Each non-zero rc also prints a greppable FAIL=<token> on stderr for
the human reading the log:

  0  extracted + judged (incl. a run with no targeted rows and a legitimate miss)
  1  a required report (area.rpt / qor.rpt) absent          -> FAIL=missing
  3  report present but an anchor absent (no 'Total cell area', no 'Critical Path
     Slack'), or the WNS summary contradicts the per-group slack -> FAIL=unparseable

FORMAT — grounded against real Synopsys DC L-2016.03-SP1 reports (sdc_controller
eval corpus). area.rpt carries one 'Total cell area:' summary line (distinct from
'Total area: undefined'); qor.rpt carries one 'Critical Path Slack:' line per
'Timing Path Group' block — the worst setup slack is the min across groups, NOT the
first listed — plus a design-level 'Design  WNS: ... Number of Violating Paths:'
summary used as a consistency cross-check. On any format surprise (an anchor that
won't parse, or a summary that contradicts the per-group slack) the parser fails
loud (exit 3) rather than emitting an unreadable number as a silent pass.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

from synthesis import requirements

# ── Anchors (grounded, DC L-2016.03-SP1) ─────────────────────────────────────
# area.rpt: "Total cell area:                 65018.219263" (NOT "Total area: undefined").
_AREA_RE = re.compile(r"^\s*Total cell area\s*:\s*([0-9.]+)", re.M)
# qor.rpt: one "Critical Path Slack:   <num>" per Timing Path Group block.
_SLACK_RE = re.compile(r"Critical Path Slack\s*:\s*([-+0-9.]+)")
# qor.rpt design summary (setup): "Design  WNS: 0.00  TNS: 0.00  Number of Violating Paths: 0".
# The hold line is "Design (Hold)  WNS: ..." — `Design\s+WNS:` matches the setup line only.
_WNS_RE = re.compile(
    r"Design\s+WNS:\s*([-+0-9.]+)\s+TNS:\s*([-+0-9.]+)\s+Number of Violating Paths:\s*(\d+)",
    re.I,
)


def parse_area_um2(text: str) -> float | None:
    """Total cell area in um^2, or None when the anchor is absent."""
    m = _AREA_RE.search(text)
    return float(m.group(1)) if m else None


def parse_worst_slack_ns(text: str) -> float | None:
    """Worst setup slack = min of every per-group Critical Path Slack, or None if absent."""
    vals = [float(x) for x in _SLACK_RE.findall(text)]
    return min(vals) if vals else None


def parse_wns_summary(text: str) -> dict | None:
    """Design-level setup summary {wns, violating_paths}, or None when absent."""
    m = _WNS_RE.search(text)
    if not m:
        return None
    return {"wns": float(m.group(1)), "violating_paths": int(m.group(3))}


def run(reports_dir, target_rows) -> tuple[int, dict | None]:
    """Parse + judge every row with a target. Returns (rc, payload); payload is None on any
    non-zero rc."""
    reports_dir = Path(reports_dir)

    area_rpt = reports_dir / "area.rpt"
    qor_rpt = reports_dir / "qor.rpt"
    for rpt in (area_rpt, qor_rpt):
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

    qor_text = qor_rpt.read_text(errors="replace")
    worst = parse_worst_slack_ns(qor_text)
    if worst is None:
        print(
            f"[synthesis finalize] FAIL=unparseable no 'Critical Path Slack' line in {qor_rpt}",
            file=sys.stderr,
        )
        return 3, None
    n_groups = len(_SLACK_RE.findall(qor_text))

    # WNS cross-check: only a *present-and-contradictory* design summary trips exit 3.
    summary = parse_wns_summary(qor_text)
    if summary is not None:
        viol_by_slack = worst < 0
        viol_by_summary = summary["wns"] < 0 or summary["violating_paths"] > 0
        if viol_by_slack != viol_by_summary:
            print(
                f"[synthesis finalize] FAIL=unparseable worst Critical Path Slack "
                f"{worst} contradicts design summary "
                f"(WNS={summary['wns']}, violating_paths={summary['violating_paths']}): {qor_rpt}",
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
            "source": f"qor.rpt worst Critical Path Slack across {n_groups} group(s) (min) "
            f"— setup only; hold is timing-analysis's",
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
        ss["fail_reason"] = (
            f"netlist incomplete: dc_shell wrote no {', '.join(missing)}"
        )
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
    """Which of the three declared DC outputs are absent, as `out/*_syn.<ext>` labels."""
    return [
        f"out/*_syn.{ext}"
        for ext in ("v", "sdc", "sdf")
        if not any(p.is_file() for p in workdir.glob(f"out/*_syn.{ext}"))
    ]


_VERSION_RE = re.compile(r"^\s*Version:\s*(\S+)", re.M)


def parse_tool(area_text: str) -> str:
    """The DC version off the report header. The kernel's reap-time identity record
    covers the library environment variables and no tool version, and this stage's
    oracle IS dc_shell, so nothing else names which compiler produced the proof."""
    m = _VERSION_RE.search(area_text)
    return f"Design Compiler {m.group(1)}" if m else "Design Compiler unknown"


def enumerate_artifacts(workdir) -> list[dict]:
    """Every promotable file this run produced, present-only.

    `out/` leaves as one tree rather than a matched file set: whatever dc_shell wrote
    into it is delivered and versioned, so a name nobody anticipated cannot drop the
    netlist out of artifacts[] — promote publishes exactly what artifacts[] lists, and a
    status=pass canonical root with no netlist leaves the two downstream rules
    undispatchable. Whether the netlist is actually there is `_missing_outputs`'s job.
    """
    workdir = Path(workdir)
    out = ["out"] if (workdir / "out").is_dir() else []
    candidates = [
        *out,
        "reports/qor.rpt",
        "reports/area.rpt",
        "reports/timing_setup.rpt",
        "reports/timing_hold.rpt",
        "reports/power.rpt",
        "reports/check_design.rpt",
        "constraints.sdc",
        "constraints.local.sdc",
        "run.log",
        "scripts/dc_run.tcl",
        "scripts/rtl_load.tcl",
        "scripts/config.tcl",
    ]  # envelope.schema forbids listing result.json itself; excluded by construction
    return [{"path": p} for p in candidates if (workdir / p).exists()]


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
