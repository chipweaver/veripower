"""power.result — parse power and activity values from PrimeTime PX text reports.

Used by the power-analysis skill to populate result.json's stage_specific:
  - parse_total_power_mw       → ppa_actual[].value (mW)
  - parse_three_components     → power_by_corner[].{internal,switching,leakage}_mw
  - parse_annotation_rate      → power_by_corner[].saif_annotation_rate

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


# ── parse_annotation_rate ──────────────────────────────────────

# `report_switching_activity` prints the same table twice — under "Switching Activity Overview
# Statistics" and under "Static Probability Overview Statistics". Only the first describes
# toggle activity, so the section header is the anchor; matching the first " Nets " row would
# be luck. That row is the aggregate, the "Nets Driven by" rows below partition it, and its
# cells are `count(pct%)` ending in a bare Total.
#
# templates/scripts/ptpx.tcl reads the same row for its in-run "annotated 0%" gate, needing
# only >0. PT is the only host for the Tcl half, so anything learned here must land there too.
_SWITCHING_SECTION_RE = re.compile(
    r"Switching\s+Activity\s+Overview\s+Statistics(?P<body>.*?)(?=Static\s+Probability|\Z)",
    re.IGNORECASE | re.DOTALL,
)
# A cell is count(pct%); the width-0 rows print "0(0%)" rather than "0(0.00%)".
_NETS_ROW_RE = re.compile(
    r"^\s*Nets\s+((?:\d+\(\s*[\d.]+%\)\s+){8})(\d+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CELL_COUNT_RE = re.compile(r"(\d+)\(\s*[\d.]+%\)")


def parse_annotation_rate(path: Path | str) -> float | None:
    """Fraction of nets whose switching activity came from the SAIF, or None.

    Derived from the row's counts rather than its printed percentage: PT rounds the cell
    to two decimals, so 155931 of 155936 prints as "100.00%" and a small shortfall would
    be invisible. The eight category counts must sum to the row's Total — a reconciliation
    the report affords for free, and the thing that makes this parser worth having rather
    than a transcription. A sum that does not reconcile means the column set moved, so the
    rate is unknown (None) rather than a number derived from a misread row.
    """
    text = _read(path)
    if text is None:
        return None
    section = _SWITCHING_SECTION_RE.search(text)
    if not section:
        return None
    row = _NETS_ROW_RE.search(section.group("body"))
    if not row:
        return None
    counts = [int(c) for c in _CELL_COUNT_RE.findall(row.group(1))]
    total = int(row.group(2))
    if len(counts) != 8 or total <= 0 or sum(counts) != total:
        return None
    return counts[0] / total


_VCS_VER_RE = re.compile(r"\b([A-Z]-\d{4}\.\d{2}(?:-SP\d+)?(?:_Full64)?)\b")
_EPS_MW = 1e-6


def _parse_vcs_version(log_path: Path | str) -> str:
    text = _read(log_path)
    if not text:
        return "unknown"
    m = _VCS_VER_RE.search(text)
    return m.group(1) if m else "unknown"


def run(plan_path, workdir, targets_json) -> tuple[int, dict]:
    """Assemble + judge. Returns (rc, payload): rc 0 = parsed+judged (incl ppa-miss), non-zero =
    deterministic data failure (FAIL=<token> on stderr). The payload is returned on BOTH paths —
    build_result folds it either way — and never written to a sidecar, because result.json
    already carries every field of it. Never writes result.json."""
    workdir = Path(workdir)

    scenarios = json.loads(
        (Path(plan_path) / "power-scenarios.json").read_text(encoding="utf-8")
    )
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
        rate = parse_annotation_rate(sa)

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
                    "corner_intent": corner,
                    "sequence_ref": seq,
                    "duration_cycles": dur,
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
                "saif_annotation_rate": rate,
                "corner_intent": corner,
                "sequence_ref": seq,
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
        return 1, payload

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
    return 0, payload


STAGE = "power-analysis"

# Everything the payload carries except `verdict` folds straight through.
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
        f"[power finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _fold(payload: dict) -> dict:
    """Copy through the keys the payload actually carries (ppa_gate_skipped only
    appears when targets=[]); never invent absent keys."""
    return {k: payload[k] for k in _FOLD_KEYS if k in payload}


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
    ]  # files AND dirs; envelope.schema forbids self-listing result.json (excluded by construction)
    return [{"path": pth} for pth in candidates if (workdir / pth).exists()]


def build_result(
    workdir,
    module,
    plan_path,
    targets,
    fix_owner=None,
    fail_reason=None,
    failure_kind=None,
) -> int:
    """Assemble the lean power-analysis result.json. Reuses run() for the PT-PX gate
    (in-process, per-scenario assembly verbatim); its payload ALREADY carries the
    stage_specific fields + verdict, so this is thin — fold the fields through, set
    status/failure_kind/fail_reason, enumerate artifacts, write the envelope.
    Returns 0 (result.json written, pass or fail). A raise -> finalize() exit 2 (BLOCKED).

    Three things this verb cannot derive, so the caller states them:

    fix_owner — which rule must act. The reports say what failed; whose artifact is at
    fault is the caller's reading.

    fail_reason — the cause of a run that produced no gradeable reports: a missing
    external reference, a license, a non-zero `make`. Supplying it IS the declaration of
    failure, so it short-circuits the gate — which cannot run anyway, since the reports
    it parses are the thing that never landed.

    failure_kind — infra or tooling for such a declaration. Absent reports look identical
    whether the flow never started or died mid-run, and only the caller saw which."""
    workdir = Path(workdir)

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

    rc, data = run(plan_path, workdir, targets)  # reuse the gate verbatim
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
    workdir,
    module,
    scaffold,
    ppa_targets,
    fix_owner=None,
    fail_reason=None,
    failure_kind=None,
) -> int:
    """Parse PT-PX reports, judge the power_mw PPA gate, write the lean result.json.
    exit 0 = written (pass or fail); exit 2 = BLOCKED (an empty --fail-reason, one
    without a --failure-kind, or any internal raise) — never conflated with status=fail.
    `scaffold` is the simulation-plan workdir (build_result's `plan_path`);
    `ppa_targets` is the ppa_targets JSON (build_result's `targets`)."""
    if fail_reason is not None:
        if not fail_reason.strip():
            print(
                "[power finalize] BLOCKED: --fail-reason must be a non-empty "
                "one-line cause",
                file=sys.stderr,
            )
            return 2
        if not failure_kind:
            print(
                "[power finalize] BLOCKED: --fail-reason needs --failure-kind "
                "{infra,tooling}",
                file=sys.stderr,
            )
            return 2
    try:
        return build_result(
            workdir,
            module,
            scaffold,
            ppa_targets,
            fix_owner,
            fail_reason,
            failure_kind,
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[power finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
