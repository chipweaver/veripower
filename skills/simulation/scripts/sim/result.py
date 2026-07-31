#!/usr/bin/env python3
"""sim finalize — assemble the lean simulation result.json at the given exit phase.

result.json's sole owner. --phase final re-derives the exit verdict in-process from
materialization_errors, compute_gate and coverage_gate (earliest failing wave wins), folds the reaped verify verdict, and
writes pass|fail; no gate's fail can be argued past it. The early-exit phases
(env-blocked/smoke/conformance/regress/verify-blocked) write the status=fail envelope,
with --failure-phase picking the schema failure_phase where the call-site spans several and the
companion fields keyed off the resolved failure_phase. Exit 0 = result.json written (pass or fail);
exit 2 = BLOCKED (internal raise) — never conflated with status=fail.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from sim._gate import _load_thresholds, coverage_gate, materialization_errors
from sim._plan import load_plan
from sim.review import compute_gate

STAGE = "simulation"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts, fix_owner=None) -> dict:
    """fix_owner rides on a failure only, and only when the caller named one: its ABSENCE is
    what decide reads as "this stage cannot tell", so it must never serialize empty."""
    if status == "fail" and fix_owner:
        stage_specific = {**stage_specific, "fix_owner": fix_owner}
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
        f"[sim finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _final_gate(workdir: Path, plan_dir: Path, thresholds: Path, conformance_review):
    """Re-derive the exit verdict in-process from materialization_errors, compute_gate and
    coverage_gate.
    Returns (ok, verdict, failure_phase, fail_reason); the earliest wave to fail wins, in the
    order the waves ran: materialization, conformance review, coverage.

    The conformance leg is the one the orchestrator could otherwise walk past. The other two
    re-derive a verdict nobody else held; this one re-derives a verdict the main thread was
    already handed and told not to override, which is worth nothing until something other than
    the overriding party checks it."""
    scaffold_doc = load_plan(plan_dir)
    d1_errs = materialization_errors(Path(workdir), scaffold_doc)
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
    flagged = compute_gate(Path(conformance_review).read_text(encoding="utf-8"))[
        "flagged"
    ]
    if flagged:
        return (
            False,
            verdict,
            "conformance",
            f"conformance gate tripped on {', '.join(flagged)}"[:300],
        )
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
    fix_owner=None,
) -> int:
    """Assemble the lean simulation result.json for the given exit phase.
    final -> re-derive compile/conformance/coverage from on-disk artifacts, fold the reaped
             verify verdict, write pass|fail.
    env-blocked|smoke|conformance|regress|verify-blocked -> write the early-exit
             status=fail envelope (observed_phase picks the schema failure_phase where the
             call-site spans several; companions keyed off the resolved failure_phase).
    Returns 0 (result.json written). A raise -> main() exit 2 (BLOCKED)."""
    workdir = Path(workdir)
    artifacts = enumerate_artifacts(workdir)
    verify = json.loads(Path(verify_verdict).read_text()) if verify_verdict else {}

    if phase != "final":
        ss = _early_exit_ss(phase, fail_reason, verify, observed_phase)
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=artifacts,
                fix_owner=fix_owner,
            ),
        )
        return 0

    ok, gate, fphase, freason = _final_gate(
        workdir, scaffold, thresholds, conformance_review
    )
    if not ok:
        # companions keyed off the resolved failure_phase, the same way _early_exit_ss keys
        # them, so triage reads one shape per phase whichever call site wrote it.
        ss = {"failure_phase": fphase, "fail_reason": freason}
        if fphase == "coverage":
            ss["coverage_extractable"] = gate["coverage_extractable"]
            ss["dims"] = gate["dims"]
        _write_result(
            workdir,
            _envelope(
                module,
                status="fail",
                stage_specific=ss,
                artifacts=artifacts,
                fix_owner=fix_owner,
            ),
        )
        return 0
    cases = read_case_counts(workdir)
    ss = {
        "total_cases": cases["total"],
        "passed": cases["passed"],
        "failed": cases["failed"],
        "stimulus_iterations": verify.get("stimulus_iterations"),
        "coverage_summary": read_coverage_summary(workdir),
    }
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def read_case_counts(workdir: Path) -> dict:
    """The suite counts, read from write_summary's structured output.

    NOT from coverage-summary.txt: that file is one of two rendered views of this data for a
    human, and re-parsing a rendering to recover numbers the same tool already had in hand is
    the round trip this reads instead of repeating.
    """
    f = Path(workdir) / "case-results.json"
    # Reached only on the pass path, where `make summary` must have run; an absent
    # file is a broken pipeline step, not a benign absence -> fail loud (BLOCKED).
    if not f.is_file():
        raise FileNotFoundError(f"case-results.json missing on the pass path: {f}")
    counts = json.loads(f.read_text(encoding="utf-8"))

    def n(k):
        v = counts.get(k)
        return v if isinstance(v, int) else None

    return {
        "total": n("total_tests"),
        "passed": n("passed_tests"),
        "failed": n("failed_tests"),
    }


def read_coverage_summary(workdir: Path):
    """The dims the coverage gate just scored. Only the pass path reaches this, and the gate
    it passed already required the file and its aggregate block, so this reads rather than
    checks."""
    f = Path(workdir) / "structural-coverage.json"
    agg = json.loads(f.read_text(encoding="utf-8"))["aggregate"]
    return {k: agg.get(k) for k in ("line", "cond", "fsm", "toggle")}


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
        "conformance-review.md",
        "structural-coverage.json",
        "case-results.json",
        "coverage-summary.txt",
        "case-results-summary.md",
    ]  # envelope.schema forbids listing result.json itself; excluded by construction
    return [{"path": p} for p in candidates if (workdir / p).exists()]


def _early_exit_ss(phase, fail_reason, verify, observed_phase=None) -> dict:
    # call-site -> default schema failure_phase (overridden by observed_phase where the
    # call-site spans several).
    fp = (
        observed_phase
        or {
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
    fix_owner=None,
) -> int:
    """Assemble the lean simulation result.json. exit 0 = result.json written (pass or fail);
    exit 2 = BLOCKED, any internal raise, never conflated with status=fail. The --phase final
    argument precondition is checked in __main__.py, which maps it to exit 2 before calling
    here."""
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
            fix_owner=fix_owner,
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[sim finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
