"""synthesis.result — extract the two PPA scalars from DC reports and judge the gate.

Single owner of the synthesis "PPA self-check" step. Given a reports dir, run():
  1. remove any prior --out file (write-fresh-or-nothing),
  2. read reports/area.rpt + reports/qor.rpt,
  3. extract area_um2 (Total cell area) and timing_slack_ns (worst Critical Path
     Slack = min across all Timing Path Group blocks, NOT the first listed),
  4. cross-check the worst slack against the design WNS / violating-path summary,
  5. judge area<=area_target and slack>=slack_target (each target optional),
  6. on success write --out (ppa-actual.json) with verdict + ppa_actual + violations.

Exit codes (each non-zero also prints a greppable FAIL=<token> on stderr):
  0  extracted + judged (incl. a vacuous no-targets pass and a legitimate
     PPA-miss verdict="fail")
  1  a required report (area.rpt / qor.rpt) absent          -> FAIL=missing
  3  report present but an anchor absent (no 'Total cell area', no 'Critical Path
     Slack'), or the WNS summary contradicts the per-group slack -> FAIL=unparseable
  2  usage error                                            -> ERROR: usage

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


def run(reports_dir, out_path, area_target, slack_target) -> int:
    reports_dir = Path(reports_dir)
    out_path = Path(out_path)

    # Write-fresh-or-nothing: clear any prior output up front.
    if out_path.exists():
        out_path.unlink()

    area_rpt = reports_dir / "area.rpt"
    qor_rpt = reports_dir / "qor.rpt"
    for rpt in (area_rpt, qor_rpt):
        if not rpt.is_file():
            print(
                f"[synthesis finalize] FAIL=missing required report not found: {rpt}",
                file=sys.stderr,
            )
            return 1

    area = parse_area_um2(area_rpt.read_text(errors="replace"))
    if area is None:
        print(
            f"[synthesis finalize] FAIL=unparseable no 'Total cell area' line in {area_rpt}",
            file=sys.stderr,
        )
        return 3

    qor_text = qor_rpt.read_text(errors="replace")
    slacks = [float(x) for x in _SLACK_RE.findall(qor_text)]
    if not slacks:
        print(
            f"[synthesis finalize] FAIL=unparseable no 'Critical Path Slack' line in {qor_rpt}",
            file=sys.stderr,
        )
        return 3
    worst = min(slacks)

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
            return 3

    # Judge — each target is optional; a missing target is not gated.
    violations: list[dict] = []
    if area_target is not None and area > area_target:
        violations.append({"dim": "area_um2", "target": area_target, "actual": area})
    if slack_target is not None and worst < slack_target:
        violations.append(
            {"dim": "timing_slack_ns", "target": slack_target, "actual": worst}
        )
    verdict = "fail" if violations else "pass"

    payload = {
        "verdict": verdict,
        "ppa_actual": [
            {"dim": "area_um2", "value": area, "source": "area.rpt Total cell area"},
            {
                "dim": "timing_slack_ns",
                "value": worst,
                "source": f"qor.rpt worst Critical Path Slack across {len(slacks)} group(s) (min)",
            },
        ],
        "violations": violations,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    sys.stdout.write(f"[synthesis finalize] Written: {out_path} (verdict={verdict})\n")
    return 0


# ── finalize: assemble the lean result.json (v4 stage-CLI-tool) ──────────────
STAGE = "synthesis"
_FAIL_REASON = {
    "missing": "synthesis report missing",
    "unparseable": "synthesis report unparseable",
}


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
    tmp.replace(workdir / "result.json")  # atomic: never observed half-written
    sys.stdout.write(
        f"[synthesis finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def build_result(workdir, module, top, area_target, slack_target) -> int:
    """Assemble the lean synthesis result.json. Reuses run() for the PPA gate
    (in-process), then derives the header + artifacts + writes the envelope.
    Returns 0 (result.json written, pass or fail). A raise -> main() exit 2 (BLOCKED)."""
    workdir = Path(workdir)
    reports = workdir / "reports"
    sidecar = workdir / "ppa-actual.json"

    rc = run(reports, sidecar, area_target, slack_target)  # reuse the gate verbatim
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
                artifacts=enumerate_artifacts(workdir, top),
            ),
        )
        return 0

    ppa = json.loads(sidecar.read_text())  # the tool's own artifact (in-process)
    status = "pass" if ppa["verdict"] == "pass" else "fail"
    area_text = (reports / "area.rpt").read_text(errors="replace")
    ss = {
        "top_module": top,
        "tool": parse_tool(area_text),
        "lib_db": read_lib_db(workdir),
        "clock": parse_clock(workdir),
        "ppa_targets": [
            d
            for d, t in (("area_um2", area_target), ("timing_slack_ns", slack_target))
            if t is not None
        ],
        "ppa_actual": ppa["ppa_actual"],
        "violations": ppa["violations"],
    }
    if status == "fail":
        ss["failure_kind"] = "ppa"
        ss["fail_reason"] = "PPA target(s) not met"
    _write_result(
        workdir,
        _envelope(
            module,
            status=status,
            stage_specific=ss,
            artifacts=enumerate_artifacts(workdir, top),
        ),
    )
    return 0


_VERSION_RE = re.compile(r"^\s*Version:\s*(\S+)", re.M)
_LIBDB_RE = re.compile(r'set ::env\(LIB_DB\)\s*"([^"]+)"')
_CLOCK_RE = re.compile(r"create_clock\s+-name\s+(\S+)\s+-period\s+([0-9.]+)")


def parse_tool(area_text: str) -> str:
    m = _VERSION_RE.search(area_text)
    return f"Design Compiler {m.group(1)}" if m else "Design Compiler unknown"


def read_lib_db(workdir):
    cfg = Path(workdir) / "scripts" / "config.tcl"
    if not cfg.is_file():
        return None
    m = _LIBDB_RE.search(cfg.read_text(errors="replace"))
    return m.group(1) if m else None


def parse_clock(workdir):
    sdc = Path(workdir) / "constraints.sdc"
    if not sdc.is_file():
        return None
    m = _CLOCK_RE.search(sdc.read_text(errors="replace"))
    return {"name": m.group(1), "period_ns": float(m.group(2))} if m else None


def enumerate_artifacts(workdir, top: str) -> list[dict]:
    workdir = Path(workdir)
    candidates = [
        f"out/{top}_syn.v",
        f"out/{top}_syn.sdc",
        f"out/{top}_syn.sdf",
        "reports/qor.rpt",
        "reports/area.rpt",
        "reports/timing_setup.rpt",
        "reports/timing_hold.rpt",
        "reports/power.rpt",
        "reports/check_design.rpt",
        "constraints.sdc",
        "run.log",
        "ppa-actual.json",
        "scripts/dc_run.tcl",
        "scripts/rtl_load.tcl",
        "scripts/config.tcl",
    ]  # envelope.schema forbids listing result.json itself; excluded by construction
    return [{"path": p} for p in candidates if (workdir / p).is_file()]


def finalize(workdir, module, top, area_target, slack_target) -> int:
    """Parse DC reports, judge PPA, write the lean result.json. exit 0 = written
    (pass or fail); exit 2 = BLOCKED (any internal raise) — never conflated with
    status=fail. (Owns the policy the deleted main() finalize branch had.)"""
    try:
        return build_result(workdir, module, top, area_target, slack_target)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[synthesis finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
