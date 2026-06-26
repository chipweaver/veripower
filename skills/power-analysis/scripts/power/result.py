"""power.result — parse power and activity values from PrimeTime PX text reports.

Used by the power-analysis skill to populate result.json's stage_specific:
  - parse_total_power_mw       → ppa_actual[].value (mW)
  - parse_three_components     → power_by_corner[].{internal,switching,leakage}_mw
  - parse_annotation_coverage  → power_by_corner[].toggle_rate
  - parse_toggle_region        → power_by_corner[].toggle_region

Source files:
  - power_flat.rpt            ← from `report_power -verbose` (no -hierarchy);
                                stable verbose-summary sentence form is more
                                regex-friendly than the hierarchical table.
  - switching_activity.rpt    ← from `report_switching_activity`.

Each function returns None on missing file / parse failure; the caller
(typically build_result_json or the subagent writing result.json) decides
whether to map None to status=fail + failures[] or to a nullable field.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

# ── Unit handling ──────────────────────────────────────────────

_UNIT_TO_MW = {"mW": 1.0, "uW": 1e-3, "W": 1e3, "nW": 1e-6}

# Header declarations PrimeTime always prints in the report preamble:
#     Dynamic Power Units = 1 W
#     Leakage Power Units = 1 W
# Used as fallback when the summary line omits an inline unit token (which
# happens when values are printed in scientific notation under the default
# "= 1 W" scaling).
_DYN_UNIT_RE = re.compile(r"Dynamic\s+Power\s+Units\s*=\s*1\s*(\w+)", re.IGNORECASE)
_LK_UNIT_RE = re.compile(r"Leakage\s+Power\s+Units\s*=\s*1\s*(\w+)", re.IGNORECASE)

_NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
_UNIT_OPT = r"(?:\s+(mW|uW|nW|W)\b)?"

# Standard PrimeTime PX verbose-summary lines (in power_flat.rpt footer):
#     Net Switching Power  = X.XXX [uW]   (XX.XX%)
#     Cell Internal Power  = X.XXX [uW]   (XX.XX%)
#     Cell Leakage Power   = X.XXX [uW]   (XX.XX%)
#     Total Power          = X.XXX [uW]   (100.00%)
# The "Cell"/"Net" prefix is a stable PrimeTime convention; the inline unit
# is optional (some configurations leave it bare and rely on the header).
_TOTAL_RE = re.compile(r"Total\s+Power\s*=\s*" + _NUM + _UNIT_OPT, re.IGNORECASE)
_INTERNAL_RE = re.compile(
    r"Cell\s+Internal\s+Power\s*=\s*" + _NUM + _UNIT_OPT, re.IGNORECASE
)
_SWITCHING_RE = re.compile(
    r"Net\s+Switching\s+Power\s*=\s*" + _NUM + _UNIT_OPT, re.IGNORECASE
)
_LEAKAGE_RE = re.compile(
    r"Cell\s+Leakage\s+Power\s*=\s*" + _NUM + _UNIT_OPT, re.IGNORECASE
)


def _read(path: Path | str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return p.read_text()
    except OSError:
        return None


def _resolve_mw(
    value: float, inline_unit: str | None, text: str, kind: str
) -> float | None:
    """Convert (value, unit) to mW.

    inline_unit takes precedence; if absent, fall back to the relevant header
    declaration ('Leakage Power Units = 1 X' for kind='leakage', 'Dynamic
    Power Units = 1 X' otherwise). Return None when no unit can be resolved.
    """
    unit = inline_unit
    if unit is None:
        m = (_LK_UNIT_RE if kind == "leakage" else _DYN_UNIT_RE).search(text)
        if m:
            unit = m.group(1)
    if unit is None:
        return None
    factor = next(
        (f for k, f in _UNIT_TO_MW.items() if k.lower() == unit.lower()),
        None,
    )
    if factor is None:
        return None
    return value * factor


# ── parse_total_power_mw ───────────────────────────────────────


def parse_total_power_mw(path: Path | str) -> float | None:
    """Return Total Power in mW (from power_flat.rpt summary), else None."""
    text = _read(path)
    if text is None:
        return None
    m = _TOTAL_RE.search(text)
    if not m:
        return None
    value = float(m.group(1))
    return _resolve_mw(value, m.group(2), text, kind="dynamic")


# ── parse_three_components ─────────────────────────────────────


def parse_three_components(path: Path | str) -> dict[str, float] | None:
    """Return {internal_mw, switching_mw, leakage_mw} (all mW), or None.

    All three components must parse for success; any single miss → None.
    """
    text = _read(path)
    if text is None:
        return None
    m_int = _INTERNAL_RE.search(text)
    m_sw = _SWITCHING_RE.search(text)
    m_lk = _LEAKAGE_RE.search(text)
    if not (m_int and m_sw and m_lk):
        return None
    internal_mw = _resolve_mw(
        float(m_int.group(1)), m_int.group(2), text, kind="dynamic"
    )
    switching_mw = _resolve_mw(
        float(m_sw.group(1)), m_sw.group(2), text, kind="dynamic"
    )
    leakage_mw = _resolve_mw(float(m_lk.group(1)), m_lk.group(2), text, kind="leakage")
    if None in (internal_mw, switching_mw, leakage_mw):
        return None
    return {
        "internal_mw": internal_mw,
        "switching_mw": switching_mw,
        "leakage_mw": leakage_mw,
    }


# ── parse_annotation_coverage ──────────────────────────────────

# PrimeTime PX prints various forms; this regex targets the summary-style
# "Annotated cell percentage = N%" line if the version emits it. When the
# version emits only a multi-column table form, this returns None and the
# caller (typically writing toggle_rate=null) does not treat that as fatal.
_ANNOTATION_RE = re.compile(
    r"Annotated\s+cell\s+percentage\s*=\s*([0-9]*\.?[0-9]+)\s*%",
    re.IGNORECASE,
)


def parse_annotation_coverage(path: Path | str) -> float | None:
    """Return annotation coverage as fraction in [0,1], or None."""
    text = _read(path)
    if text is None:
        return None
    m = _ANNOTATION_RE.search(text)
    if not m:
        return None
    return float(m.group(1)) / 100.0


# ── parse_toggle_region ────────────────────────────────────────

_TOGGLE_REGION_RE = re.compile(
    r"SAIF\s+time\s+interval\s*=\s*([0-9]+)\s+to\s+([0-9]+)\s*(ns|ps|us)?",
    re.IGNORECASE,
)


def parse_toggle_region(path: Path | str) -> str | None:
    """Return toggle region as '<start><unit>-<end><unit>', or None."""
    text = _read(path)
    if text is None:
        return None
    m = _TOGGLE_REGION_RE.search(text)
    if not m:
        return None
    start = m.group(1)
    end = m.group(2)
    unit = (m.group(3) or "ns").lower()
    return f"{start}{unit}-{end}{unit}"


_VCS_VER_RE = re.compile(r"\b([A-Z]-\d{4}\.\d{2}(?:-SP\d+)?(?:_Full64)?)\b")
_EPS_MW = 1e-6


def _parse_vcs_version(log_path: Path | str) -> str:
    text = _read(log_path)
    if not text:
        return "unknown"
    m = _VCS_VER_RE.search(text)
    return m.group(1) if m else "unknown"


def run(plan_path, workdir, targets_json, out_path) -> int:
    """Assemble + judge → power-actual.json. exit 0 = parsed+judged (incl ppa-miss);
    non-zero = deterministic data failure (FAIL=<token> on stderr). Never writes result.json."""
    workdir = Path(workdir)
    out_path = Path(out_path)
    if out_path.exists():
        out_path.unlink()

    scenarios = json.loads(Path(plan_path).read_text()).get("power_scenarios", [])
    targets = json.loads(targets_json) if targets_json else []

    failures: list[dict] = []
    saif_artifacts: list[dict] = []
    ppa_actual: list[dict] = []
    power_by_corner: list[dict] = []

    for s in scenarios:
        sid = s.get("id", "")
        seq = s.get("sequence_ref", "")
        corner = s.get("corner_intent", "")
        dur = s.get("duration_cycles")
        saif = workdir / "saif" / f"{sid}.saif"
        size = saif.stat().st_size if saif.is_file() else 0
        flat = workdir / "reports_ptpx" / sid / "power_flat.rpt"
        sa = workdir / "reports_ptpx" / sid / "switching_activity.rpt"

        total = parse_total_power_mw(flat)
        three = parse_three_components(flat)
        rate = parse_annotation_coverage(sa)
        region = parse_toggle_region(sa)

        scenario_failed = False

        if size == 0:
            failures.append(
                {
                    "id": sid,
                    "phase": "run",
                    "category": "saif_dump",
                    "error_summary": f"SAIF empty or absent: {saif.name}",
                    "log_excerpt": "gls-run-log.txt",
                }
            )
            scenario_failed = True
        else:
            saif_artifacts.append(
                {
                    "id": sid,
                    "saif_path": f"saif/{sid}.saif",
                    "canonical_path": f"saif/_dedup/{seq}.saif",
                    "format": "saif",
                    "corner_intent": corner,
                    "sequence_ref": seq,
                    "duration_cycles": dur,
                    "size_bytes": size,
                }
            )

        if total is None:
            summ = (
                f"power_flat.rpt not found: {flat.name}"
                if not flat.is_file()
                else f"power_flat.rpt missing Total Power: {flat.name}"
            )
            failures.append(
                {
                    "id": sid,
                    "phase": "parse",
                    "category": "ptpx_data",
                    "error_summary": summ,
                    "log_excerpt": f"reports_ptpx/{sid}/power_flat.rpt",
                }
            )
            scenario_failed = True

        internal = three["internal_mw"] if three else None
        switching = three["switching_mw"] if three else None
        leakage = three["leakage_mw"] if three else None

        if (
            total is not None
            and three is not None
            and abs(total - (internal + switching + leakage))
            > max(_EPS_MW, 1e-2 * abs(total))
        ):
            failures.append(
                {
                    "id": sid,
                    "phase": "parse",
                    "category": "ptpx_data",
                    "error_summary": f"power_mw {total} != internal+switching+leakage",
                    "log_excerpt": f"reports_ptpx/{sid}/power_flat.rpt",
                }
            )
            scenario_failed = True

        # P1: a scenario with any deterministic failure has untrustworthy numbers → null them.
        ppa_actual.append(
            {
                "dim": "power_mw",
                "value": None if scenario_failed else total,
                "scenario_id": sid,
                "source": f"reports_ptpx/{sid}/power_flat.rpt",
            }
        )
        power_by_corner.append(
            {
                "scenario_id": sid,
                "power_mw": None if scenario_failed else total,
                "internal_mw": None if scenario_failed else internal,
                "switching_mw": None if scenario_failed else switching,
                "leakage_mw": None if scenario_failed else leakage,
                "toggle_rate": rate,
                "toggle_region": region,
                "corner_intent": corner,
                "sequence_ref": seq,
                "analysis_mode": "averaged",
            }
        )

    compile_info = {"vcs_version": _parse_vcs_version(workdir / "gls-compile-log.txt")}

    if failures:
        payload = {
            "verdict": "fail",
            "failure_kind": "tooling",
            "saif_artifacts": saif_artifacts,
            "compile_info": compile_info,
            "failures": failures,
            "ppa_actual": ppa_actual,
            "violations": [],
            "power_by_corner": power_by_corner,
        }
        out_path.write_text(json.dumps(payload, indent=2) + "\n")
        f0 = failures[0]
        summ = f0["error_summary"]
        if "!=" in summ:
            token = "invariant"
        elif "not found" in summ:
            token = "report_missing"
        elif f0["category"] == "saif_dump":
            token = "saif_empty"
        else:
            token = "unparseable"
        print(
            f"[power finalize] FAIL={token}:{f0.get('id', '')} {summ}",
            file=sys.stderr,
        )
        return 1

    violations: list[dict] = []
    for entry in ppa_actual:
        sid, actual = entry["scenario_id"], entry["value"]
        for t in targets:
            if t.get("dim") != "power_mw":
                continue
            tsid = t.get("scenario_id")
            if tsid is not None and tsid != sid:
                continue
            if actual > t["target"]:
                violations.append(
                    {
                        "dim": "power_mw",
                        "target": t["target"],
                        "actual": actual,
                        "scenario_id": sid,
                    }
                )

    verdict = "fail" if violations else "pass"
    payload = {
        "verdict": verdict,
        "saif_artifacts": saif_artifacts,
        "compile_info": compile_info,
        "failures": [],
        "ppa_actual": ppa_actual,
        "violations": violations,
        "power_by_corner": power_by_corner,
    }
    if violations:
        payload["failure_kind"] = "ppa"
    if not targets:
        payload["ppa_gate_skipped"] = True
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"[power finalize] Written: {out_path} (verdict={verdict})")
    return 0


STAGE = "power-analysis"

# These 7 keys (everything the sidecar carries except `verdict`) fold straight through.
_FOLD_KEYS = (
    "saif_artifacts",
    "compile_info",
    "failures",
    "ppa_actual",
    "violations",
    "power_by_corner",
    "ppa_gate_skipped",
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
    (workdir / "result.json").write_text(json.dumps(env, indent=2) + "\n")
    sys.stdout.write(
        f"[power finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _fold(sidecar: dict) -> dict:
    """Copy through the keys the sidecar actually carries (ppa_gate_skipped only
    appears when targets=[]); never invent absent keys."""
    return {k: sidecar[k] for k in _FOLD_KEYS if k in sidecar}


def _tooling_reason(data: dict) -> str:
    f = (data.get("failures") or [{}])[0]
    summ = f.get("error_summary", "PT-PX data failure")
    sid = f.get("id")
    return f"{summ} (scenario {sid})" if sid else summ


def enumerate_artifacts(workdir: Path) -> list[dict]:
    workdir = Path(workdir)
    candidates = [
        "env.sh",
        "Makefile",
        "README.md",
        "scripts",
        "scaffold",
        "tb_filelist_abs.f",
        "simv",
        "simv.daidir",
        "saif",
        "reports_ptpx",
        "gls-compile-log.txt",
        "gls-run-log.txt",
        "ptpx.log",
        "make.out",
        "power-actual.json",
    ]  # files AND dirs; envelope.schema forbids self-listing result.json (excluded by construction)
    return [{"path": pth} for pth in candidates if (workdir / pth).exists()]


def build_result(workdir, module, plan_path, targets) -> int:
    """Assemble the lean power-analysis result.json. Reuses run() for the PT-PX gate
    (in-process, per-scenario assembly verbatim); the sidecar ALREADY carries the 7
    stage_specific fields + verdict, so this is thin — fold the fields through, set
    status/failure_kind/fail_reason, enumerate artifacts, write the envelope.
    Returns 0 (result.json written, pass or fail). A raise -> main() exit 2 (BLOCKED)."""
    workdir = Path(workdir)
    sidecar = workdir / "power-actual.json"

    rc = run(plan_path, workdir, targets, sidecar)  # reuse the gate verbatim
    data = json.loads(sidecar.read_text())  # sidecar written on exit 0 AND exit 1
    ss = _fold(data)

    if rc != 0:
        # Parser exit 1: failures[] populated, verdict=fail, failure_kind=tooling.
        ss["failure_kind"] = data.get("failure_kind", "tooling")
        ss["fail_reason"] = _tooling_reason(data)
        status = "fail"
    elif data["verdict"] == "fail":
        # PPA-gate miss: power_mw exceeded target.
        status = "fail"
        ss["failure_kind"] = "ppa"
        ss["fail_reason"] = "power_mw exceeds target"
    else:
        status = "pass"

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


def finalize(workdir, module, scaffold, ppa_targets) -> int:
    """Parse PT-PX reports, judge the power_mw PPA gate, write the lean result.json.
    exit 0 = written (pass or fail); exit 2 = BLOCKED (any internal raise) — never
    conflated with status=fail. (Owns the policy the deleted main() finalize branch had.)
    `scaffold` is the scaffold-specification.json path (build_result's `plan_path`);
    `ppa_targets` is the ppa_targets JSON (build_result's `targets`)."""
    try:
        return build_result(workdir, module, scaffold, ppa_targets)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[power finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
