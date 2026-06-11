#!/usr/bin/env python3
"""aggregate_signoff.py — own the frontend-signoff gate, envelope, and machine docs.

frontend-signoff is the pipeline's terminal aggregator. This script reads the 6
upstream canonical result.json envelopes + fixed evidence paths (JSON/filesystem
only — it does NOT parse design.md / <child>.md markdown), decides pass/fail, and
writes checklist.md (full) + traceability.md (report/tool-version skeleton) +
result.json (script-authored envelope). The agent composes the feature->evidence
matrix into traceability.md afterward.

Verdict / exit contract:
  exit 0, status=pass  — all envelopes pass, all evidence reachable, traceability
                         inputs readable (when spec passed).
  exit 0, status=fail  — any envelope missing/unparseable/!=pass, any evidence
                         unreachable, or spec passed but manifest/<child>.md
                         unreadable. A clean fail verdict is still written.
  exit !=0             — the script itself cannot operate (workdir unwritable,
                         internal exception); result.json not (fully) written;
                         the subagent emits STATUS: BLOCKED.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

# (stage, path relative to asic_root) — the 6 upstream canonical envelopes.
UPSTREAM = [
    ("power-analysis", "Verification/power-analysis/result.json"),
    ("timing-analysis", "Design/timing-analysis/result.json"),
    ("simulation", "Verification/simulation/result.json"),
    ("synthesis", "Design/synthesis/result.json"),
    ("lint-cdc", "Design/lint-cdc/result.json"),
    ("specification", "Design/specification/result.json"),
]


def derive_asic_root(workdir: Path) -> Path:
    """asic/<module>/ from the run workdir asic/<module>/frontend-signoff/runs/<N>/."""
    return Path(workdir).parents[2]


def read_envelopes(asic_root: Path) -> tuple[dict, list[str]]:
    """Return (by_stage, failures).

    by_stage[stage] = parsed envelope dict (or None when missing/unparseable).
    failures lists one greppable reason per stage that is missing / unparseable /
    not status==pass.
    """
    by_stage: dict = {}
    failures: list[str] = []
    for stage, rel in UPSTREAM:
        p = asic_root / rel
        if not p.is_file():
            by_stage[stage] = None
            failures.append(f"{stage}: envelope missing ({rel})")
            continue
        try:
            env = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            by_stage[stage] = None
            failures.append(f"{stage}: envelope unparseable ({rel})")
            continue
        by_stage[stage] = env
        if env.get("status") != "pass":
            failures.append(f"{stage}: not pass (status={env.get('status')!r})")
    return by_stage, failures


# Fixed evidence paths (relative to asic_root). power_hier.rpt is globbed below.
EVIDENCE = [
    "Design/specification/design.md",
    "Design/lint-cdc/lint-report.txt",
    "Design/lint-cdc/cdc-report.txt",
    "Verification/simulation/case-results-summary.md",
    "Design/timing-analysis/timing-report.txt",
    "Design/synthesis/reports/qor.rpt",
]
_POWER_GLOB = "Verification/power-analysis/reports_ptpx/*/power_hier.rpt"


def resolve_evidence(asic_root: Path) -> tuple[list[dict], list[str]]:
    """Resolve every evidence path to a concrete record + collect failures.

    Returns (records, failures). records = [{"path": <rel>, "on_disk": bool}] for
    the 6 fixed paths plus the power report (the runtime dir id is globbed to its
    concrete path). failures = one greppable reason per unreachable path; the power
    glob is fail-loud — 0 matches is unreachable, >1 is a conflict (never silently
    pick one). records carry the path list both checklist.md and traceability.md
    render (the auditable "these reports are on disk, here are the paths").
    """
    records: list[dict] = []
    failures: list[str] = []
    for rel in EVIDENCE:
        on_disk = (asic_root / rel).is_file()
        records.append({"path": rel, "on_disk": on_disk})
        if not on_disk:
            failures.append(f"evidence unreachable: {rel}")
    matches = sorted(asic_root.glob(_POWER_GLOB))
    if not matches:
        records.append({"path": _POWER_GLOB, "on_disk": False})
        failures.append(f"evidence unreachable: {_POWER_GLOB} (0 matches)")
    elif len(matches) > 1:
        rels = ", ".join(str(m.relative_to(asic_root)) for m in matches)
        records.append({"path": _POWER_GLOB, "on_disk": False})
        failures.append(
            f"evidence conflict: {_POWER_GLOB} ({len(matches)} matches: {rels})"
        )
    else:
        records.append(
            {"path": str(matches[0].relative_to(asic_root)), "on_disk": True}
        )
    return records, failures


def check_traceability_inputs(asic_root: Path) -> list[str]:
    """Existence/readability of the agent's matrix inputs (manifest.json + each
    <child>.md). NOT parsed — the script never reads §5 markdown. Called only when
    specification passed: spec=pass yet inputs unreadable is an upstream contract
    violation, so it must fail loud (don't let the agent sign with no matrix source).
    """
    spec = asic_root / "Design/specification"
    manifest_p = spec / "manifest.json"
    if not manifest_p.is_file():
        return [f"traceability input unreadable: {manifest_p.relative_to(asic_root)}"]
    try:
        manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [f"traceability input unparseable: {manifest_p.relative_to(asic_root)}"]
    failures: list[str] = []
    for child in manifest.get("children", []):
        doc = child.get("doc")
        if not doc or not (spec / doc).is_file():
            failures.append(
                f"traceability input unreadable: Design/specification/{doc}"
            )
    return failures


def extract_ppa(by_stage: dict) -> dict:
    """Best-effort headline PPA pulled from the parsed envelopes. Non-gating; every
    field is None when absent (synthesis/timing carry no tool version)."""
    out = {
        "area_um2": None,
        "setup_wns_ns": None,
        "hold_wns_ns": None,
        "power_mw": None,
        "vcs_version": None,
    }

    syn_ss = (by_stage.get("synthesis") or {}).get("stage_specific") or {}
    for item in syn_ss.get("ppa_actual", []) or []:
        if item.get("dim") == "area_um2":
            out["area_um2"] = item.get("value")

    tim_ss = (by_stage.get("timing-analysis") or {}).get("stage_specific") or {}
    timing = tim_ss.get("timing") or {}
    out["setup_wns_ns"] = (timing.get("setup") or {}).get("worst_slack_ns")
    out["hold_wns_ns"] = (timing.get("hold") or {}).get("worst_slack_ns")

    pwr_ss = (by_stage.get("power-analysis") or {}).get("stage_specific") or {}
    # power ppa_actual[] may carry one entry per scenario_id — surface the
    # worst-case (max) power_mw as the headline, not an arbitrary "last" one.
    power_vals = [
        item.get("value")
        for item in (pwr_ss.get("ppa_actual") or [])
        if item.get("dim") == "power_mw" and item.get("value") is not None
    ]
    out["power_mw"] = max(power_vals) if power_vals else None
    out["vcs_version"] = (pwr_ss.get("compile_info") or {}).get("vcs_version")
    return out


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _ppa_rows(ppa: dict) -> str:
    def v(x):
        return "n/a" if x is None else x

    return (
        f"| Area (um^2) | {v(ppa['area_um2'])} |\n"
        f"| Setup WNS (ns) | {v(ppa['setup_wns_ns'])} |\n"
        f"| Hold WNS (ns) | {v(ppa['hold_wns_ns'])} |\n"
        f"| Power (mW) | {v(ppa['power_mw'])} |\n"
    )


def _evidence_rows(evidence: list[dict]) -> str:
    return "".join(
        f"| {r['path']} | {'yes' if r['on_disk'] else 'NO'} |\n" for r in evidence
    )


def render_checklist(
    module: str,
    by_stage: dict,
    ppa: dict,
    evidence: list[dict],
    *,
    status: str,
    failures: list[str],
) -> str:
    rows = "".join(
        f"| {stage} | {(by_stage.get(stage) or {}).get('status', 'MISSING')} |\n"
        for stage, _ in UPSTREAM
    )
    fail_block = "none\n" if not failures else "".join(f"- {f}\n" for f in failures)
    return (
        f"# Frontend Sign-off Checklist — {module}\n\n"
        f"Generated: {_now_iso()}\n"
        f"Verdict: {status}\n\n"
        f"## Stage pass summary\n\n| Stage | status |\n|---|---|\n{rows}\n"
        f"## Evidence\n\n| Path | On disk |\n|---|---|\n{_evidence_rows(evidence)}\n"
        f"## Headline PPA\n\n| Metric | Value |\n|---|---|\n{_ppa_rows(ppa)}\n"
        f"## Failures\n\n{fail_block}"
    )


def render_traceability_skeleton(module: str, ppa: dict, evidence: list[dict]) -> str:
    return (
        f"# Traceability — {module}\n\n"
        f"> Report index & tool-version index below are machine-generated by "
        f"aggregate_signoff.py.\n"
        f"> The feature->evidence matrix and executive summary are composed by the "
        f"sign-off agent.\n\n"
        f"## Report index\n\n| Report | On disk |\n|---|---|\n{_evidence_rows(evidence)}\n"
        f"## Tool-version index (best-effort)\n\n| Tool | Version |\n|---|---|\n"
        f"| VCS (power GLS) | {ppa['vcs_version'] or 'n/a'} |\n"
        f"| Synthesis / STA | n/a (no version key in result.json) |\n\n"
        f"## Feature -> evidence matrix\n\n"
        f"<!-- agent: fill from manifest.json + design.md §1.3 + each <child>.md §5; "
        f"map every feature/check to the passing evidence that demonstrates it -->\n\n"
        f"## Executive summary\n\n"
        f"<!-- agent: cross-stage synthesis (all-pass, features traced, headline "
        f"WNS/area/power, coverage, waivers, anything worth a human glance) -->\n"
    )


def build_envelope(
    module: str, *, status: str, fail_reason: str | None, artifacts: list[dict]
) -> dict:
    stage_specific: dict = {} if status == "pass" else {"fail_reason": fail_reason}
    return {
        "schema_version": 1,
        "stage": "frontend-signoff",
        "module": module,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": artifacts,
        "stage_specific": stage_specific,
    }


def run(workdir: str, module: str) -> int:
    """Compute the verdict, write checklist.md + traceability.md + result.json.

    Returns 0 for both pass and fail (a verdict was written). Raising propagates
    to main() -> exit 2 (the BLOCKED path): the script could not operate.
    """
    workdir_p = Path(workdir)
    asic_root = derive_asic_root(workdir_p)

    by_stage, failures = read_envelopes(asic_root)
    failures = list(failures)
    evidence, ev_failures = resolve_evidence(asic_root)
    failures += ev_failures
    spec = by_stage.get("specification")
    if spec is not None and spec.get("status") == "pass":
        failures += check_traceability_inputs(asic_root)

    status = "pass" if not failures else "fail"
    fail_reason = None if status == "pass" else "; ".join(failures)
    ppa = extract_ppa(by_stage)

    (workdir_p / "checklist.md").write_text(
        render_checklist(
            module, by_stage, ppa, evidence, status=status, failures=failures
        ),
        encoding="utf-8",
    )
    (workdir_p / "traceability.md").write_text(
        render_traceability_skeleton(module, ppa, evidence), encoding="utf-8"
    )

    # Defensive post-write assertion: a failed doc write is a program exception,
    # not a status=fail. Raising here lands in the BLOCKED path.
    if (
        not (workdir_p / "checklist.md").is_file()
        or not (workdir_p / "traceability.md").is_file()
    ):
        raise RuntimeError("checklist.md / traceability.md were not written")

    env = build_envelope(
        module,
        status=status,
        fail_reason=fail_reason,
        artifacts=[{"path": "checklist.md"}, {"path": "traceability.md"}],
    )
    (workdir_p / "result.json").write_text(
        json.dumps(env, indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(
        f"[aggregate_signoff] Written: {workdir_p / 'result.json'} (status={status})\n"
    )
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="aggregate_signoff.py",
        description="Aggregate upstream envelopes + evidence into the frontend-signoff verdict.",
    )
    ap.add_argument("--workdir", required=True, help="frontend-signoff run workdir")
    ap.add_argument("--module", required=True, help="module name")
    try:
        args = ap.parse_args(argv[1:])
    except SystemExit as exc:
        if exc.code not in (0, None):
            print("[aggregate_signoff] ERROR: usage", file=sys.stderr)
            return 2
        return 0
    try:
        return run(args.workdir, args.module)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[aggregate_signoff] FAIL=internal {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
