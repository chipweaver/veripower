#!/usr/bin/env python3
"""Close functional verification from current artifacts and the stage owner's judgment.

Final closure checks materialization, review markers, coverage and case results.
An explicit fail_reason records unresolved work. Exit 0 means a pass/fail result was
written; exit 2 means closure could not complete.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from sim.checks import (
    check_review_flagged,
    coverage_gate,
    coverage_rows,
    materialization_errors,
)
from sim.plan import load_plan

STAGE = "simulation"


def final_gate(workdir: Path, plan_dir: Path, requirements: Path, check_review):
    """Re-derive the exit verdict in-process from the three primitives in sim.checks.
    Returns (ok, verdict, phase, fail_reason); the earliest wave to fail wins, in the
    order the waves ran: materialization, check-adequacy review, coverage.

    Unresolved review markers are retained as a closure barrier. The stage owner also
    assesses unmarked findings against their evidence before invoking final closure."""
    scaffold_doc = load_plan(plan_dir)
    materialization_issues = materialization_errors(Path(workdir), scaffold_doc)
    rows = coverage_rows(Path(requirements))
    coverage_path = Path(workdir) / "structural-coverage.json"
    coverage = (
        json.loads(coverage_path.read_text(encoding="utf-8"))
        if coverage_path.is_file()
        else None
    )
    dut_instance = f"{scaffold_doc['top']}_tb_top.u_dut"
    coverage_issues, judged = coverage_gate(coverage, rows, dut_instance)
    verdict = {
        "coverage_extractable": not coverage_issues or bool(judged),
        "requirements": judged,
        "scope": dut_instance,
    }
    if materialization_issues:
        return (False, verdict, "compile", "; ".join(materialization_issues)[:300])
    flagged = check_review_flagged(check_review)
    if flagged:
        return (
            False,
            verdict,
            "check-review",
            f"check-adequacy gate tripped on {', '.join(flagged)}"[:300],
        )
    if coverage_issues:
        return (False, verdict, "coverage", "; ".join(coverage_issues)[:300])
    return (True, verdict, None, None)


def read_case_counts(workdir: Path) -> dict:
    """The suite counts, read from write_summary's structured output rather than re-parsed out
    of the rendering it writes beside it."""
    f = Path(workdir) / "case-results.json"
    # Reached only on the pass path, where `make summary` must have run; an absent
    # file is a broken pipeline step, not a benign absence -> fail loud (BLOCKED).
    if not f.is_file():
        raise FileNotFoundError(f"case-results.json missing on the pass path: {f}")
    counts = json.loads(f.read_text(encoding="utf-8"))

    keys = ("total_tests", "passed_tests", "failed_tests", "not_run_tests")
    for key in keys:
        value = counts.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"case-results.json needs a nonnegative integer {key}")
    if counts["total_tests"] != counts["passed_tests"] + counts["failed_tests"]:
        raise ValueError("case-results.json total does not match passed + failed")
    if counts["total_tests"] + counts["not_run_tests"] == 0:
        raise ValueError("case-results.json contains no declared tests")
    return dict(
        zip(("total", "passed", "failed", "not_run"), (counts[k] for k in keys))
    )


def read_coverage_summary(workdir: Path, dut: str):
    """The dims the coverage gate just scored, and the scope they were scored in. Only the pass
    path reaches this, and the gate it passed already required the DUT's instance subtree, so
    this reads rather than checks.

    Which tree the number covers is not recorded beside it: the gate scores the DUT's row or
    fails, so there is no second answer for a field to disambiguate."""
    f = Path(workdir) / "structural-coverage.json"
    per = json.loads(f.read_text(encoding="utf-8"))["per_instance"]
    row = next(m for m in per if m.get("name") == dut)
    return {k: row.get(k) for k in ("line", "cond", "fsm", "toggle")}


def enumerate_artifacts(workdir: Path) -> list[dict]:
    workdir = Path(workdir)
    candidates = [
        "evidence",
        "Makefile",
        "env.sh",
        "filelist.f",
        "rtl_filelist.f",
        "tb",
        "scripts",
        "tests",
        "regression-log.txt",
        "logs",
        "check-review.md",
        "structural-coverage.json",
        "cov_merge",
        "case-results.json",
        "case-results-summary.md",
    ]  # envelope.schema forbids listing result.json itself; excluded by construction
    return [{"path": p} for p in candidates if (workdir / p).exists()]


def finalize(
    workdir,
    *,
    phase,
    scaffold=None,
    requirements=None,
    check_review=None,
    fail_reason=None,
    fix_owner=None,
) -> int:
    """Assess the stage and write its result. Input or I/O errors leave no current result."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if (
        phase != "final"
        and (not fail_reason)
        or (fail_reason is not None and (not fail_reason.strip()))
    ):
        print("[sim finalize] BLOCKED: empty --fail-reason", file=sys.stderr)
        return 2

    def _write_result(*, status, stage_specific, artifacts):
        if status == "fail" and fix_owner:
            stage_specific = {**stage_specific, "fix_owner": fix_owner}
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
        print(f"[sim finalize] Written: {result_path} (status={status})")
        return 0

    try:
        workdir = Path(workdir)
        artifacts = enumerate_artifacts(workdir)
        if phase != "final" or fail_reason is not None:
            return _write_result(
                status="fail",
                stage_specific={"fail_reason": fail_reason},
                artifacts=artifacts,
            )
        ok, gate, failed_phase, failure_reason = final_gate(
            workdir, scaffold, requirements, check_review
        )
        if not ok:
            stage_specific = {"fail_reason": failure_reason}
            if failed_phase == "coverage":
                stage_specific["coverage_extractable"] = gate["coverage_extractable"]
                stage_specific["requirements"] = gate["requirements"]
            return _write_result(
                status="fail", stage_specific=stage_specific, artifacts=artifacts
            )
        cases = read_case_counts(workdir)
        if cases["not_run"] or cases["failed"]:
            reasons = []
            if cases["failed"]:
                reasons.append(f"{cases['failed']} tests failed")
            if cases["not_run"]:
                reasons.append(f"{cases['not_run']} declared tests produced no result")
            stage_specific = {
                "total_cases": cases["total"],
                "passed": cases["passed"],
                "failed": cases["failed"],
                "fail_reason": "; ".join(reasons),
            }
            return _write_result(
                status="fail", stage_specific=stage_specific, artifacts=artifacts
            )
        stage_specific = {
            "total_cases": cases["total"],
            "passed": cases["passed"],
            "failed": cases["failed"],
            "coverage_summary": read_coverage_summary(workdir, gate["scope"]),
            "requirements": gate["requirements"],
        }
        return _write_result(
            status="pass", stage_specific=stage_specific, artifacts=artifacts
        )
    except (OSError, ValueError) as exc:
        print(f"[sim finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
