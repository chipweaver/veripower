#!/usr/bin/env python3
"""sim finalize — assemble the lean simulation result.json at the given exit phase.

result.json's sole owner. --phase final re-derives the compile/coverage verdict in-process via
the shared thin_d1 + coverage_gate (earlier phase wins), reads the conformance gate via the pure
compute_gate, folds the reaped verify verdict, and writes pass|fail. The early-exit phases
(prerequisite/env-blocked/smoke/conformance/regress/verify-blocked) write the status=fail envelope,
with --failure-phase picking the schema failure_phase where the call-site spans several and the
companion fields keyed off the resolved failure_phase. Exit 0 = result.json written (pass or fail);
exit 2 = BLOCKED (internal raise) — never conflated with status=fail.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

from sim._gate import _load_thresholds, coverage_gate, thin_d1
from sim.classify import plan_digest
from sim.review import compute_gate

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
    tmp = workdir / "result.json.tmp"
    tmp.write_text(json.dumps(env, indent=2) + "\n")
    tmp.replace(
        workdir / "result.json"
    )  # atomic: never observed half-written
    sys.stdout.write(
        f"[sim finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
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
    plan=None,
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

    # Compute plan_digest only for freeze-eligible phases (pass path and regress/coverage
    # fail paths carry a complete TB that the classifier may reuse). verify-blocked is
    # deliberately excluded — it maps failure_phase=regress but must NOT get a digest
    # so the next run classifies patch (copy-first) rather than freeze (spec §4: verify-blocked -> patch).
    digest = (
        plan_digest(scaffold, plan)
        if (scaffold and plan and phase in ("final", "regress"))
        else None
    )

    if phase != "final":
        ss = _early_exit_ss(
            phase, fail_reason, verify, observed_phase, conformance_review
        )
        if digest:
            ss["plan_digest"] = digest
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
        if digest:
            ss["plan_digest"] = digest
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
    if digest:
        ss["plan_digest"] = digest
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


# --- pass-summary derivations (Task 2) ---------------------------------------
_KV = re.compile(r"^(\w+):\s*(\S+)\s*$", re.M)


def read_case_counts(workdir: Path) -> dict:
    f = Path(workdir) / "coverage-summary.txt"
    # Reached only on the pass path, where `make summary` must have run; an absent
    # summary is a broken pipeline step, not a benign absence -> fail loud (BLOCKED).
    if not f.is_file():
        raise FileNotFoundError(f"coverage-summary.txt missing on the pass path: {f}")
    kv = dict(_KV.findall(f.read_text(encoding="utf-8")))

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
    return compute_gate({"findings": findings})["gate"]  # single-homed reduction


def conformance_advisory(review_path) -> list[dict]:
    findings = _findings(review_path) or []
    flagged = set(compute_gate({"findings": findings})["flagged"])
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
    if fp in ("smoke", "regress") and "failing_cases" in verify:
        ss["failing_cases"] = verify["failing_cases"]
    if fp == "coverage":  # Rule-B verify route-out
        for k in ("coverage_gaps", "gaps_not_in_testpoints", "gaps_in_testpoints"):
            if k in verify:
                ss[k] = verify[k]
    if phase == "conformance":
        # the gating subset, re-derived in-process from the on-disk conformance-review.json
        # (reaped state, not orchestrator narration — single-homed via compute_gate).
        # --phase conformance is only reached on a gate=trip, where the main thread has
        # assembled conformance-review.json; an absent file is a caller contract violation.
        if not conformance_review or not Path(conformance_review).is_file():
            raise RuntimeError(
                "finalize --phase conformance requires an assembled conformance-review.json "
                f"(got: {conformance_review!r})"
            )
        findings = _findings(conformance_review) or []
        flagged = set(compute_gate({"findings": findings})["flagged"])
        ss["conformance_findings"] = [f for f in findings if f.get("tp_id") in flagged]
    return ss


def finalize(
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
    plan=None,
) -> int:
    """Assemble the lean simulation result.json. exit 0 = result.json written (pass or fail);
    exit 2 = BLOCKED (any internal raise) — never conflated with status=fail. (Owns the policy
    the deleted main() finalize-subcommand had; the --phase-final arg precondition lives in
    __main__.py, which maps it to exit 2 before calling here.)"""
    try:
        return build_result(
            workdir,
            module,
            phase=phase,
            scaffold=scaffold,
            thresholds=thresholds,
            conformance_review=conformance_review,
            verify_verdict=verify_verdict,
            fail_reason=fail_reason,
            observed_phase=observed_phase,
            plan=plan,
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[sim finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
