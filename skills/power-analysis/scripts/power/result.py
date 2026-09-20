"""power.result — parse power and activity values from PrimeTime PX text reports.

Used by the power-analysis skill to populate result.json's stage_specific:
  - parse_total_power_mw       → measurements[].value (mW)
  - parse_three_components     → power_by_scenario[].{internal,switching,leakage}_mw
  - parse_toggled_net_fraction → power_by_scenario[].toggled_net_fraction

Source files:
  - power_flat.rpt            ← from `report_power -verbose` (no -hierarchy);
                                stable verbose-summary sentence form is more
                                regex-friendly than the hierarchical table.
  - saif/<id>.saif            ← from the gate-level run's $toggle_report.
  - saif/<id>.status          ← explicit experiment completion after checks/capture.

Each function returns None on missing file / parse failure; the caller
(finalize) decides
whether to map None to status=fail + failures[] or to a nullable field.
"""

from __future__ import annotations

import datetime
import json
import math
import operator
import re
import sys
from pathlib import Path

from power import requirements
from power.scenarios import load

# ── Unit handling ──────────────────────────────────────────────

POWER_UNIT_TO_MILLIWATTS = {"mW": 1.0, "uW": 1e-3, "W": 1e3, "nW": 1e-6}

# Header declarations PrimeTime always prints in the report preamble:
#     Dynamic Power Units = 1 W
#     Leakage Power Units = 1 W
# Used as fallback when the summary line omits an inline unit token (which
# happens when values are printed in scientific notation under the default
# "= 1 W" scaling).
DYNAMIC_POWER_UNIT_PATTERN = re.compile(
    r"Dynamic\s+Power\s+Units\s*=\s*1\s*(\w+)", re.IGNORECASE
)
LEAKAGE_POWER_UNIT_PATTERN = re.compile(
    r"Leakage\s+Power\s+Units\s*=\s*1\s*(\w+)", re.IGNORECASE
)

NUMBER_PATTERN = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
UNIT_OPT = r"(?:\s+(mW|uW|nW|W)\b)?"

# Standard PrimeTime PX verbose-summary lines (in power_flat.rpt footer):
#     Net Switching Power  = X.XXX [uW]   (XX.XX%)
#     Cell Internal Power  = X.XXX [uW]   (XX.XX%)
#     Cell Leakage Power   = X.XXX [uW]   (XX.XX%)
#     Total Power          = X.XXX [uW]   (100.00%)
# The "Cell"/"Net" prefix is a stable PrimeTime convention; the inline unit
# is optional (some configurations leave it bare and rely on the header).
TOTAL_RE = re.compile(
    r"Total\s+Power\s*=\s*" + NUMBER_PATTERN + UNIT_OPT, re.IGNORECASE
)
INTERNAL_RE = re.compile(
    r"Cell\s+Internal\s+Power\s*=\s*" + NUMBER_PATTERN + UNIT_OPT, re.IGNORECASE
)
SWITCHING_RE = re.compile(
    r"Net\s+Switching\s+Power\s*=\s*" + NUMBER_PATTERN + UNIT_OPT, re.IGNORECASE
)
LEAKAGE_RE = re.compile(
    r"Cell\s+Leakage\s+Power\s*=\s*" + NUMBER_PATTERN + UNIT_OPT, re.IGNORECASE
)


def read_report_text(path: Path | str) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    return p.read_text()


def resolve_mw(
    reported_power: float, inline_unit: str | None, text: str, kind: str
) -> float | None:
    """Convert (value, unit) to mW.

    inline_unit takes precedence; if absent, fall back to the relevant header
    declaration ('Leakage Power Units = 1 X' for kind='leakage', 'Dynamic
    Power Units = 1 X' otherwise). Return None when no unit can be resolved.
    """
    unit = inline_unit
    if unit is None:
        unit_match = (
            LEAKAGE_POWER_UNIT_PATTERN
            if kind == "leakage"
            else DYNAMIC_POWER_UNIT_PATTERN
        ).search(text)
        if unit_match:
            unit = unit_match.group(1)
    if unit is None:
        return None
    mw_per_report_unit = next(
        (f for k, f in POWER_UNIT_TO_MILLIWATTS.items() if k.lower() == unit.lower()),
        None,
    )
    if mw_per_report_unit is None:
        return None
    power_mw = reported_power * mw_per_report_unit
    return power_mw if math.isfinite(power_mw) and power_mw >= 0 else None


# ── parse_total_power_mw ───────────────────────────────────────


def parse_total_power_mw(path: Path | str) -> float | None:
    """Return Total Power in mW (from power_flat.rpt summary), else None."""
    text = read_report_text(path)
    if text is None:
        return None
    m = TOTAL_RE.search(text)
    if not m:
        return None
    value = float(m.group(1))
    return resolve_mw(value, m.group(2), text, kind="dynamic")


# ── parse_three_components ─────────────────────────────────────


def parse_three_components(path: Path | str) -> dict[str, float] | None:
    """Return {internal_mw, switching_mw, leakage_mw} (all mW), or None.

    All three components must parse for success; any single miss → None.
    """
    text = read_report_text(path)
    if text is None:
        return None
    m_int = INTERNAL_RE.search(text)
    m_sw = SWITCHING_RE.search(text)
    m_lk = LEAKAGE_RE.search(text)
    if not (m_int and m_sw and m_lk):
        return None
    internal_mw = resolve_mw(
        float(m_int.group(1)), m_int.group(2), text, kind="dynamic"
    )
    switching_mw = resolve_mw(float(m_sw.group(1)), m_sw.group(2), text, kind="dynamic")
    leakage_mw = resolve_mw(float(m_lk.group(1)), m_lk.group(2), text, kind="leakage")
    if None in (internal_mw, switching_mw, leakage_mw):
        return None
    return {
        "internal_mw": internal_mw,
        "switching_mw": switching_mw,
        "leakage_mw": leakage_mw,
    }


# ── parse_toggled_net_fraction ─────────────────────────────────

# The SAIF's own per-net toggle counts: `(TC <n>)`, one per net, beside (T0 …) (T1 …).
# Nothing PT reports carries this. `report_switching_activity` and
# `report_activity_file_check` both describe where the activity came from, not how much
# there was, and on a real netlist their output is byte-identical for a SAIF whose design
# ran and one whose design sat still.
TC_RE = re.compile(rb"\(TC (\d+)\)")


def parse_toggled_net_fraction(path: Path | str) -> float | None:
    """Fraction of the SAIF's nets that toggled at least once. None when the file is
    absent or carries no TC entry at all (a format surprise, not a quiet zero)."""
    saif_path = Path(path)
    if not saif_path.is_file():
        return None
    net_count = 0
    toggled_net_count = 0
    with saif_path.open("rb") as stream:
        for line in stream:
            for toggle_count_match in TC_RE.finditer(line):
                net_count += 1
                if toggle_count_match.group(1) != b"0":
                    toggled_net_count += 1
    if net_count == 0:
        return None
    return toggled_net_count / net_count


VCS_VER_RE = re.compile(r"\b([A-Z]-\d{4}\.\d{2}(?:-SP\d+)?(?:_Full64)?)\b")
POWER_SUM_TOLERANCE_MW = 1e-6


def run(plan_path, workdir, target_rows) -> tuple[int, dict]:
    """Assemble + judge. Returns (rc, payload): rc 0 = parsed+judged (incl a missed bound), non-zero =
    deterministic data failure (FAIL=<token> on stderr). The payload is returned on BOTH paths —
    finalize folds it either way — and never written to a sidecar, because result.json
    already carries every field of it. Never writes result.json."""
    workdir = Path(workdir)

    scenarios = load(plan_path)

    failures: list[dict] = []
    saif_artifacts: list[dict] = []
    measurements: list[dict] = []
    power_by_scenario: list[dict] = []

    for scenario_id in scenarios:
        saif = workdir / "saif" / f"{scenario_id}.saif"
        saif_bytes = saif.stat().st_size if saif.is_file() else 0
        power_report = workdir / "reports_ptpx" / scenario_id / "power_flat.rpt"

        total_power_mw = parse_total_power_mw(power_report)
        components_mw = parse_three_components(power_report)
        toggled_net_fraction = parse_toggled_net_fraction(saif)

        scenario_failed = False

        if saif_bytes == 0:
            failures.append(
                {
                    "id": scenario_id,
                    "phase": "run",
                    "category": "saif_dump",
                    "error_summary": f"SAIF empty or absent: {saif.name}",
                    "log_excerpt": f"saif/{scenario_id}.run.log",
                }
            )
            scenario_failed = True
        else:
            saif_artifacts.append(
                {
                    "id": scenario_id,
                    "saif_path": f"saif/{scenario_id}.saif",
                }
            )

        status_path = workdir / "saif" / f"{scenario_id}.status"
        status = (
            status_path.read_text(errors="replace").strip()
            if status_path.is_file()
            else None
        )
        if status != "PASS":
            failures.append(
                {
                    "id": scenario_id,
                    "phase": "run",
                    "category": "experiment",
                    "error_summary": (
                        f"gate-level run reported {status}: saif/{scenario_id}.status"
                        if status
                        else f"gate-level run left no verdict: saif/{scenario_id}.status absent"
                    ),
                    "log_excerpt": f"saif/{scenario_id}.run.log",
                }
            )
            scenario_failed = True

        activity = read_report_text(
            workdir / "reports_ptpx" / scenario_id / "switching_activity.rpt"
        )
        annotated = re.search(
            r"^\s*Nets\s+(\d+)\(([0-9.]+)%\)", activity or "", re.MULTILINE
        )
        if not annotated or int(annotated.group(1)) == 0:
            failures.append(
                {
                    "id": scenario_id,
                    "phase": "ptpx",
                    "category": "ptpx_data",
                    "error_summary": "missing or zero SAIF net annotation",
                    "log_excerpt": f"reports_ptpx/{scenario_id}/switching_activity.rpt",
                }
            )
            scenario_failed = True

        if toggled_net_fraction is None and saif_bytes:
            failures.append(
                {
                    "id": scenario_id,
                    "phase": "run",
                    "category": "saif_dump",
                    "error_summary": "SAIF has no activity entries",
                    "log_excerpt": f"saif/{scenario_id}.saif",
                }
            )
            scenario_failed = True

        if total_power_mw is None:
            summ = (
                f"power_flat.rpt not found: {power_report.name}"
                if not power_report.is_file()
                else f"power_flat.rpt missing Total Power: {power_report.name}"
            )
            failures.append(
                {
                    "id": scenario_id,
                    "phase": "parse",
                    "category": "ptpx_data",
                    "error_summary": summ,
                    "log_excerpt": f"reports_ptpx/{scenario_id}/power_flat.rpt",
                }
            )
            scenario_failed = True

        if components_mw is None:
            failures.append(
                {
                    "id": scenario_id,
                    "phase": "parse",
                    "category": "ptpx_data",
                    "error_summary": "missing or invalid power components",
                    "log_excerpt": f"reports_ptpx/{scenario_id}/power_flat.rpt",
                }
            )
            scenario_failed = True

        internal_mw = components_mw["internal_mw"] if components_mw else None
        switching_mw = components_mw["switching_mw"] if components_mw else None
        leakage_mw = components_mw["leakage_mw"] if components_mw else None

        if (
            total_power_mw is not None
            and components_mw is not None
            and abs(total_power_mw - (internal_mw + switching_mw + leakage_mw))
            > max(POWER_SUM_TOLERANCE_MW, 1e-2 * abs(total_power_mw))
        ):
            failures.append(
                {
                    "id": scenario_id,
                    "phase": "parse",
                    "category": "ptpx_data",
                    "error_summary": f"power_mw {total_power_mw} != internal+switching+leakage",
                    "log_excerpt": f"reports_ptpx/{scenario_id}/power_flat.rpt",
                }
            )
            scenario_failed = True

        # A scenario with any deterministic failure has untrustworthy numbers → null them.
        measurements.append(
            {
                "dim": "power_mw",
                "value": None if scenario_failed else total_power_mw,
                "scenario_id": scenario_id,
                "source": f"reports_ptpx/{scenario_id}/power_flat.rpt",
            }
        )
        power_by_scenario.append(
            {
                "scenario_id": scenario_id,
                "power_mw": None if scenario_failed else total_power_mw,
                "internal_mw": None if scenario_failed else internal_mw,
                "switching_mw": None if scenario_failed else switching_mw,
                "leakage_mw": None if scenario_failed else leakage_mw,
                "toggled_net_fraction": toggled_net_fraction,
            }
        )

    compile_log = read_report_text(workdir / "gls-compile-log.txt")
    version_match = VCS_VER_RE.search(compile_log or "")
    compile_info = {
        "vcs_version": version_match.group(1) if version_match else "unknown"
    }

    if failures:
        payload = {
            "measurements": measurements,
            "verdict": "fail",
            "saif_artifacts": saif_artifacts,
            "compile_info": compile_info,
            "failures": failures,
            "power_by_scenario": power_by_scenario,
        }
        f0 = failures[0]
        summ = f0["error_summary"]
        if f0["category"] == "experiment":
            token = "experiment"
        elif "!=" in summ:
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
        return 1, payload

    # Judge — one entry per targeted row, with the engineer's own operator. A row naming a
    # scenario this run did not measure, or any row when nothing was measured, cannot be judged.
    judged: list[dict] = []
    dims = sorted({measurement["dim"] for measurement in measurements})
    for requirement in target_rows:
        target = requirement["target"]
        dimension = target["dim"]
        if dimension not in dims:
            # Without this the loop compares whatever measurements holds — a row asking for an
            # area bound was judged met against a number of milliwatts, silently and at exit 0.
            raise ValueError(
                f"{requirement['id']} is judged by power-analysis with target dim {dimension!r}, which this "
                f"stage does not measure (it measures {dims}) — the row names the wrong judge, "
                f"or the dim is wrong"
            )
        scenario_id = target.get("scenario")
        picked = [
            measurement
            for measurement in measurements
            if measurement["dim"] == dimension
            and (scenario_id is None or measurement["scenario_id"] == scenario_id)
        ]
        if not picked:
            raise ValueError(
                f"{requirement['id']} needs a measured {dimension}"
                + (f" for scenario {scenario_id!r}" if scenario_id else "")
                + "; this run measured none"
            )
        judged.append(
            {
                "id": requirement["id"],
                "met": all(
                    COMPARISONS[target["op"]](measurement["value"], target["value"])
                    for measurement in picked
                ),
                "actual": (min if target["op"] in (">", ">=") else max)(
                    measurement["value"] for measurement in picked
                ),
                "measured": (
                    f"{dimension} from "
                    + ", ".join(sorted(measurement["source"] for measurement in picked))
                    if len(picked) == 1
                    else f"worst {dimension} across {len(picked)} scenarios: "
                    + ", ".join(sorted(measurement["source"] for measurement in picked))
                ),
            }
        )

    payload = {
        # What this run read, returned to the caller; the envelope carries only the verdicts,
        # each naming the measurement it came from.
        "measurements": measurements,
        "saif_artifacts": saif_artifacts,
        "compile_info": compile_info,
        "failures": [],
        "requirements": judged,
        "power_by_scenario": power_by_scenario,
    }
    return 0, payload


STAGE = "power-analysis"
COMPARISONS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}

# Everything the payload carries folds straight through.


def enumerate_artifacts(workdir: Path) -> list[dict]:
    """Publish the experiment and reusable products, excluding disposable working data."""
    workdir = Path(workdir)
    excluded = {
        "result.json",
        "result.json.tmp",
        "dispatch.json",
        "runs",
        "work",
        ".pending",
    }
    return [
        {"path": p.name} for p in sorted(workdir.iterdir()) if p.name not in excluded
    ]


def finalize(workdir, plan, rows, declared, fix_owner=None, fail_reason=None) -> int:
    """Assess the stage and write its result. Input or I/O errors leave no current result."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if fail_reason is not None:
        if not fail_reason.strip():
            print(
                "[power finalize] BLOCKED: --fail-reason must be a non-empty one-line cause",
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
        print(f"[power finalize] Written: {result_path} (status={status})")
        return 0

    try:
        workdir = Path(workdir)
        if fail_reason is not None:
            stage_specific = {"fail_reason": fail_reason}
            if fix_owner:
                stage_specific["fix_owner"] = fix_owner
            return _write_result(
                status="fail",
                stage_specific=stage_specific,
                artifacts=enumerate_artifacts(workdir),
            )
        exit_code, data = run(plan, workdir, [r for r in rows if "target" in r])
        stage_specific = {
            key: data[key]
            for key in (
                "saif_artifacts",
                "compile_info",
                "failures",
                "power_by_scenario",
            )
        }
        if exit_code != 0:
            failure = data["failures"][0]
            stage_specific["fail_reason"] = (
                f"{failure['error_summary']} (scenario {failure['id']})"
            )
            status = "fail"
        else:
            judged = requirements.merge(rows, data["requirements"], declared)
            stage_specific["requirements"] = judged
            unmet = [entry["id"] for entry in judged if not entry["met"]]
            status = "fail" if unmet else "pass"
            if unmet:
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
        print(f"[power finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
