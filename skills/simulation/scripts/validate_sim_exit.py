#!/usr/bin/env python3
"""simulation stage exit self-check (one pass at sim end). Mirrors validate_scaffold.py.

Checks, against the produced workdir + scaffold-specification.json + defaults.yaml:
  thin-D1  materialization defense: every sequences[]/agents[] SV file present; no TODO residue
           (any form -- a completed TB carries zero "TODO"; canonical templates carry none).
  D5       coverage extractable: structural-coverage.json present with an aggregate block.
  D6       coverage gate: each defaults.yaml.coverage_thresholds dim >= threshold
           (a dim whose measured value is null/absent -- e.g. a DUT with no FSM -- is skipped).

Exit non-zero with a readable, fix-oriented message on any failure (status truth = exit code,
NOT agent narration). Prints a one-line JSON verdict on stdout that the agent copies into
result.json stage_specific (additionalProperties): no new schema, no result.json write here.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import yaml

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))  # make the sibling conformance module importable

import validate_conformance_review as vcr  # noqa: E402 — needs the sys.path insert above; gate reduction single-homed there

# Policy: ANY "TODO" in a materialized TB == unfinished work -> fail (a completed TB carries
# zero "TODO" anywhere). Match the bare word so no stub format escapes the gate. This REQUIRES
# the canonical templates to carry no non-marker "TODO" prose (base_seq.sv uses NOTE; the
# scaffold provenance headers avoid "TODO"), so the only "TODO" left in a *generated* file is
# an UNFILLED fill marker (TODO(sequence)/TODO(rm)/
# the no-seq test's "TODO: Start sequences here." ...), which is exactly what we want to fail on.
_TODO_RE = re.compile(r"TODO")


def _load_thresholds(path: Path) -> dict:
    """Read the coverage_thresholds block from defaults.yaml (dim -> float)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: float(v) for k, v in (data.get("coverage_thresholds") or {}).items()}


def thin_d1(workdir: Path, scaffold: dict) -> list[str]:
    """Materialization defense: required SV files present + no TODO residue (any form). Most
    files are guaranteed by derive_scaffold; this catches agent-side deletion/overwrite + any
    unfilled stub. Canonical templates carry zero non-marker TODO prose, so a match
    here is always a real unfilled marker."""
    module = scaffold.get("module", "")
    errs: list[str] = []
    for seq in scaffold.get("sequences", []):
        f = workdir / "tb/uvm/seq" / f"{module}_{seq.get('name')}_seq.sv"
        if not f.is_file():
            errs.append(
                f"missing sequence file {f.relative_to(workdir)} "
                f"(derive_scaffold generates it; was it deleted/overwritten?)"
            )
    for ag in scaffold.get("agents", []):
        name = ag.get("name")
        need = [f"{module}_{name}_monitor.sv", f"{module}_{name}_agent.sv"]
        if ag.get("mode") == "active":
            need.append(f"{module}_{name}_driver.sv")
        for fn in need:
            f = workdir / "tb/uvm/agent" / fn
            if not f.is_file():
                errs.append(f"missing agent file {f.relative_to(workdir)}")
    tb = workdir / "tb" / "uvm"
    if tb.is_dir():
        for sv in sorted(set(tb.rglob("*.sv")) | set(tb.rglob("*.svh"))):
            if _TODO_RE.search(sv.read_text(encoding="utf-8", errors="ignore")):
                errs.append(
                    f"TODO residue in {sv.relative_to(workdir)} "
                    f"(fill the scaffold; no TODO may survive in a completed TB)"
                )
    return errs


def coverage_gate(cov: dict | None, thresholds: dict) -> tuple[list[str], dict]:
    """D5 (extractable) + D6 (dims >= threshold; null dim skipped). Returns (errors, dims_report)."""
    if (
        cov is None
        or not isinstance(cov.get("aggregate"), dict)
        or not cov["aggregate"]
    ):
        return (
            [
                "coverage not extractable: structural-coverage.json missing or empty "
                "(urg did not produce a parseable report; cannot gate -> fail, never claim met)"
            ],
            {},
        )
    agg = cov["aggregate"]
    errs: list[str] = []
    dims: dict = {}
    for dim, thr in thresholds.items():
        if (
            dim not in agg
        ):  # urg never measured this dim -> cannot gate it -> fail (not silent skip)
            dims[dim] = {"value": "absent", "threshold": thr, "pass": False}
            errs.append(
                f"{dim} threshold configured but absent from the coverage report "
                f"(urg did not measure it; cannot gate)"
            )
            continue
        val = agg[dim]
        if (
            val is None
        ):  # measured as N/A ('--', e.g. a DUT with no FSM) -> skip, do not fail
            dims[dim] = {"value": None, "threshold": thr, "pass": True, "skipped": True}
            continue
        ok = val >= thr
        dims[dim] = {"value": val, "threshold": thr, "pass": ok}
        if not ok:
            errs.append(f"{dim} coverage {val} < threshold {thr}")
    return errs, dims


# ── finalize: assemble the lean result.json (v4 stage-CLI-tool) ──────────────
STAGE = "simulation"


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
        f"[validate_sim_exit] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _final_gate(workdir: Path, scaffold: Path, thresholds: Path):
    """Reuse thin_d1 + coverage_gate IN-PROCESS to re-derive the compile/coverage verdict.
    Returns (ok, verdict, failure_phase, fail_reason). Earlier phase wins (thin-D1 -> compile)."""
    scaffold_doc = json.loads(Path(scaffold).read_text(encoding="utf-8"))
    d1_errs = thin_d1(Path(workdir), scaffold_doc)
    thr = _load_thresholds(Path(thresholds))
    cov_path = Path(workdir) / "structural-coverage.json"
    cov = (
        json.loads(cov_path.read_text(encoding="utf-8")) if cov_path.is_file() else None
    )
    cov_errs, dims = coverage_gate(cov, thr)
    verdict = {
        "coverage_extractable": cov is not None and bool((cov or {}).get("aggregate")),
        "dims": dims,
    }
    if d1_errs:
        return (False, verdict, "compile", "; ".join(d1_errs)[:300])
    if cov_errs:
        return (False, verdict, "coverage", "; ".join(cov_errs)[:300])
    return (True, verdict, None, None)


def build_result(
    workdir,
    module,
    *,
    phase,
    scaffold=None,
    thresholds=None,
    conformance_review=None,
    verify_verdict=None,
    fail_reason=None,
    observed_phase=None,
) -> int:
    """Assemble the lean simulation result.json for the given exit phase.
    final -> re-derive compile/coverage from on-disk artifacts (pure thin_d1/coverage_gate),
             read conformance via compute_gate, fold the reaped verify verdict, write pass|fail.
    prerequisite|env-blocked|smoke|conformance|regress|verify-blocked -> write the early-exit
             status=fail envelope (observed_phase picks the schema failure_phase where the
             call-site spans several; companions keyed off the resolved failure_phase).
    Returns 0 (result.json written). A raise -> main() exit 2 (BLOCKED)."""
    workdir = Path(workdir)
    artifacts = enumerate_artifacts(workdir)
    verify = json.loads(Path(verify_verdict).read_text()) if verify_verdict else {}

    if phase != "final":
        ss = _early_exit_ss(
            phase, fail_reason, verify, observed_phase, conformance_review
        )
        _write_result(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0

    ok, gate, fphase, freason = _final_gate(workdir, scaffold, thresholds)
    if not ok:
        ss = {
            "failure_phase": fphase,
            "fail_reason": freason,
            "coverage_extractable": gate["coverage_extractable"],
            "dims": gate["dims"],
        }
        _write_result(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0
    cases = read_case_counts(workdir)
    ss = {
        "total_cases": cases["total"],
        "passed": cases["passed"],
        "failed": cases["failed"],
        "stimulus_iterations": verify.get("stimulus_iterations"),
        "coverage_summary": read_coverage_summary(workdir),
        "conformance_gate": conformance_gate_label(conformance_review),
        "conformance_advisory": conformance_advisory(conformance_review),
    }
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


# --- pass-summary derivations (Task 2) ---------------------------------------
_KV = re.compile(r"^(\w+):\s*(\S+)\s*$", re.M)


def read_case_counts(workdir: Path) -> dict:
    f = Path(workdir) / "coverage-summary.txt"
    kv = dict(_KV.findall(f.read_text(encoding="utf-8"))) if f.is_file() else {}

    def n(k):
        try:
            return int(kv[k])
        except (KeyError, ValueError):
            return None

    return {
        "total": n("total_tests"),
        "passed": n("passed_tests"),
        "failed": n("failed_tests"),
    }


def read_coverage_summary(workdir: Path):
    f = Path(workdir) / "structural-coverage.json"
    if not f.is_file():
        return None
    agg = (json.loads(f.read_text(encoding="utf-8")) or {}).get("aggregate") or {}
    return {k: agg.get(k) for k in ("line", "cond", "fsm", "toggle")}


def _findings(review_path):
    p = Path(review_path) if review_path else None
    if not p or not p.is_file():
        return None
    return (json.loads(p.read_text(encoding="utf-8")) or {}).get("findings", [])


def conformance_gate_label(review_path):
    findings = _findings(review_path)
    if findings is None:
        return None
    return vcr.compute_gate({"findings": findings})["gate"]  # single-homed reduction


def conformance_advisory(review_path) -> list[dict]:
    findings = _findings(review_path) or []
    flagged = set(vcr.compute_gate({"findings": findings})["flagged"])
    out = []
    for f in findings:
        if f.get("tp_id") in flagged:
            continue  # gating findings -> failure_phase=conformance, not the advisory list
        out.append(
            {
                "tp_id": f.get("tp_id"),
                "category": f.get("category"),
                "severity": f.get("severity"),
                "note": f.get("summary"),
            }
        )  # summary VERBATIM
    return out


def enumerate_artifacts(workdir: Path) -> list[dict]:
    workdir = Path(workdir)
    candidates = [
        "Makefile",
        "env.sh",
        "filelist.f",
        "rtl_filelist.f",
        "tb/uvm",
        "scripts",
        "tests/testlist.json",
        "regression-log.txt",
        "logs",
        "verify-handoff.json",
        "conformance-review.json",
        "structural-coverage.json",
        "coverage-summary.txt",
        "case-results-summary.md",
    ]  # envelope.schema forbids listing result.json itself; excluded by construction
    return [{"path": p} for p in candidates if (workdir / p).exists()]


def _early_exit_ss(
    phase, fail_reason, verify, observed_phase=None, conformance_review=None
) -> dict:
    # call-site -> default schema failure_phase (overridden by observed_phase where the
    # call-site spans several).
    fp = (
        observed_phase
        or {
            "prerequisite": "prerequisite",
            "env-blocked": "compile",
            "smoke": "smoke",
            "conformance": "conformance",
            "regress": "regress",
            "verify-blocked": "regress",
        }[phase]
    )
    ss = {"failure_phase": fp, "fail_reason": fail_reason or ""}
    # companions keyed off the RESOLVED failure_phase, not the call-site:
    if fp == "compile" and verify.get("compile_rounds") is not None:
        ss["compile_rounds"] = verify["compile_rounds"]
    if fp in ("smoke", "regress") and "failing_cases" in verify:
        ss["failing_cases"] = verify["failing_cases"]
    if fp == "coverage":  # Rule-B verify route-out
        for k in ("coverage_gaps", "gaps_not_in_testpoints", "gaps_in_testpoints"):
            if k in verify:
                ss[k] = verify[k]
    if phase == "conformance":
        # the gating subset, re-derived in-process from the on-disk conformance-review.json
        # (reaped state, not orchestrator narration — single-homed via compute_gate).
        findings = _findings(conformance_review) or []
        flagged = set(vcr.compute_gate({"findings": findings})["flagged"])
        ss["conformance_findings"] = [f for f in findings if f.get("tp_id") in flagged]
    return ss


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "finalize":
        ap = argparse.ArgumentParser(
            prog="validate_sim_exit.py finalize",
            description="Assemble the lean simulation result.json at the given exit phase.",
        )
        ap.add_argument("--workdir", required=True, type=Path)
        ap.add_argument("--module", required=True)
        ap.add_argument(
            "--phase",
            required=True,
            choices=[
                "prerequisite",
                "env-blocked",
                "smoke",
                "conformance",
                "regress",
                "verify-blocked",
                "final",
            ],
        )
        ap.add_argument(
            "--failure-phase",
            choices=[
                "prerequisite",
                "compile",
                "smoke",
                "conformance",
                "regress",
                "coverage",
            ],
            default=None,
            help="observed schema failure_phase when the call-site spans several "
            "(env-blocked/smoke/regress/verify-blocked); defaults per --phase",
        )
        ap.add_argument(
            "--scaffold",
            type=Path,
            help="scaffold-specification.json (required for --phase final)",
        )
        ap.add_argument(
            "--thresholds", type=Path, help="defaults.yaml (required for --phase final)"
        )
        ap.add_argument("--conformance-review", type=Path, default=None)
        ap.add_argument(
            "--verify-verdict",
            type=Path,
            default=None,
            help="reaped verify-child JSON (stimulus_iterations / failing_cases / coverage_gaps / gaps_*)",
        )
        ap.add_argument(
            "--fail-reason",
            default=None,
            help="one-line reason for an early-exit phase",
        )
        try:
            a = ap.parse_args(argv[2:])
            if a.phase == "final" and not (a.scaffold and a.thresholds):
                ap.error("--scaffold and --thresholds are required for --phase final")
        except SystemExit as exc:
            if exc.code not in (0, None):
                print("[validate_sim_exit] ERROR: usage", file=sys.stderr)
                return 2
            return 0
        try:
            return build_result(
                a.workdir,
                a.module,
                phase=a.phase,
                scaffold=a.scaffold,
                thresholds=a.thresholds,
                conformance_review=a.conformance_review,
                verify_verdict=a.verify_verdict,
                fail_reason=a.fail_reason,
                observed_phase=a.failure_phase,
            )
        except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
            print(f"[validate_sim_exit] FAIL=internal {exc}", file=sys.stderr)
            return 2
    # ── legacy exit-check CLI (UNCHANGED) ─────────────────────────────────────
    p = argparse.ArgumentParser(
        description="simulation exit self-check (thin-D1 + D5 + D6)."
    )
    p.add_argument(
        "--workdir",
        required=True,
        help="sim workdir (contains tb/uvm + structural-coverage.json)",
    )
    p.add_argument("--scaffold", required=True, help="scaffold-specification.json path")
    p.add_argument(
        "--thresholds",
        help="defaults.yaml path (coverage_thresholds); required unless --thin-only",
    )
    p.add_argument(
        "--thin-only",
        action="store_true",
        help="env-exit gate: run thin-D1 (materialization) only -- skip coverage/D5/D6; "
        "--thresholds not required. Emits a trimmed {unmaterialized, todo_residue} verdict.",
    )
    args = p.parse_args(argv[1:])
    if not args.thin_only and not args.thresholds:
        p.error("--thresholds is required unless --thin-only is set")

    workdir = Path(args.workdir).resolve()
    scaffold = json.loads(Path(args.scaffold).read_text(encoding="utf-8"))

    d1_errs = thin_d1(workdir, scaffold)

    if args.thin_only:
        # env-exit gate: materialization only. No coverage, no result.json write -- the
        # env subagent gates its own STATUS: DONE on this exit code; finalize's full run
        # remains the authoritative result.json verdict. thin-D1 fail -> failure_phase=compile
        # (the existing mapping; this presence gate does not itself route conformance).
        verdict = {
            "unmaterialized": [e for e in d1_errs if "missing" in e],
            "todo_residue": [e for e in d1_errs if "TODO" in e],
        }
        if d1_errs:
            print(json.dumps(verdict))
            sys.exit(
                "validate_sim_exit --thin-only: materialization incomplete:\n  - "
                + "\n  - ".join(d1_errs)
                + "\nFill the scaffold (no TODO may survive; all required files present), "
                "then re-run. Budget-exhausted-with-residue -> failure_phase=compile."
            )
        print(
            "validate_sim_exit --thin-only: OK (thin-D1 clean -- materialization complete)"
        )
        print(json.dumps(verdict))
        return 0

    thresholds = _load_thresholds(Path(args.thresholds))
    cov_path = workdir / "structural-coverage.json"
    cov = (
        json.loads(cov_path.read_text(encoding="utf-8")) if cov_path.is_file() else None
    )
    cov_errs, dims = coverage_gate(cov, thresholds)
    errs = d1_errs + cov_errs

    verdict = {
        "coverage_extractable": cov is not None and bool(cov.get("aggregate")),
        "dims": dims,
        "unmaterialized": [e for e in d1_errs if "missing" in e],
        "todo_residue": [e for e in d1_errs if "TODO" in e],
    }
    if errs:
        print(json.dumps(verdict))
        sys.exit(
            "validate_sim_exit: simulation exit checks failed:\n  - "
            + "\n  - ".join(errs)
            + "\nThin-D1 fails -> failure_phase=compile; coverage fails -> failure_phase=coverage. "
            "Fix the TB / stimulus and re-run (status truth is this gate, not narration)."
        )
    print(
        "validate_sim_exit: OK (thin-D1 clean, coverage extractable, all gated dims >= threshold)"
    )
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
