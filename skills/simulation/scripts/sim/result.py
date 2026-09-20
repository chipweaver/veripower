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

from sim._gate import (
    check_review_flagged,
    coverage_gate,
    coverage_rows,
    materialization_errors,
)
from sim._plan import load_plan

STAGE = "simulation"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(*, status, stage_specific, artifacts, fix_owner=None) -> dict:
    """fix_owner rides on a failure only, and only when the caller named one: its ABSENCE is
    what decide reads as "this stage cannot tell", so it must never serialize empty."""
    if status == "fail" and fix_owner:
        stage_specific = {**stage_specific, "fix_owner": fix_owner}
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
        f"[sim finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _final_gate(workdir: Path, plan_dir: Path, requirements: Path, check_review):
    """Re-derive the exit verdict in-process from the three primitives in sim._gate.
    Returns (ok, verdict, phase, fail_reason); the earliest wave to fail wins, in the
    order the waves ran: materialization, check-adequacy review, coverage.

    Unresolved review markers are retained as a closure barrier. The stage owner also
    assesses unmarked findings against their evidence before invoking final closure."""
    scaffold_doc = load_plan(plan_dir)
    d1_errs = materialization_errors(Path(workdir), scaffold_doc)
    rows = coverage_rows(Path(requirements))
    cov_path = Path(workdir) / "structural-coverage.json"
    cov = (
        json.loads(cov_path.read_text(encoding="utf-8")) if cov_path.is_file() else None
    )
    dut = f"{scaffold_doc['top']}_tb_top.u_dut"
    cov_errs, judged = coverage_gate(cov, rows, dut)
    verdict = {
        "coverage_extractable": not cov_errs or bool(judged),
        "requirements": judged,
        "scope": dut,
    }
    if d1_errs:
        return (False, verdict, "compile", "; ".join(d1_errs)[:300])
    flagged = check_review_flagged(check_review)
    if flagged:
        return (
            False,
            verdict,
            "check-review",
            f"check-adequacy gate tripped on {', '.join(flagged)}"[:300],
        )
    if cov_errs:
        return (False, verdict, "coverage", "; ".join(cov_errs)[:300])
    return (True, verdict, None, None)


def build_result(
    workdir,
    *,
    phase,
    scaffold=None,
    requirements=None,
    check_review=None,
    fail_reason=None,
    fix_owner=None,
) -> int:
    """Assemble the lean simulation result.json for the given exit phase.
    final -> judge materialization, review, coverage and case results on disk.
    fail  -> record the unresolved cause; logs and reports remain the case evidence.
    Returns 0 (result.json written). A raise -> main() exit 2 (BLOCKED)."""
    workdir = Path(workdir)
    artifacts = enumerate_artifacts(workdir)

    if phase != "final" or fail_reason is not None:
        _write_result(
            workdir,
            _envelope(
                status="fail",
                stage_specific={"fail_reason": fail_reason},
                artifacts=artifacts,
                fix_owner=fix_owner,
            ),
        )
        return 0

    ok, gate, fphase, freason = _final_gate(
        workdir, scaffold, requirements, check_review
    )
    if not ok:
        ss = {"fail_reason": freason}
        if fphase == "coverage":
            ss["coverage_extractable"] = gate["coverage_extractable"]
            ss["requirements"] = gate["requirements"]
        _write_result(
            workdir,
            _envelope(
                status="fail",
                stage_specific=ss,
                artifacts=artifacts,
                fix_owner=fix_owner,
            ),
        )
        return 0
    cases = read_case_counts(workdir)
    if cases["not_run"] or cases["failed"]:
        reasons = []
        if cases["failed"]:
            reasons.append(f"{cases['failed']} tests failed")
        if cases["not_run"]:
            reasons.append(f"{cases['not_run']} declared tests produced no result")
        ss = {
            "total_cases": cases["total"],
            "passed": cases["passed"],
            "failed": cases["failed"],
            "fail_reason": "; ".join(reasons),
        }
        _write_result(
            workdir,
            _envelope(
                status="fail",
                stage_specific=ss,
                artifacts=artifacts,
                fix_owner=fix_owner,
            ),
        )
        return 0
    ss = {
        "total_cases": cases["total"],
        "passed": cases["passed"],
        "failed": cases["failed"],
        "coverage_summary": read_coverage_summary(workdir, gate["scope"]),
        "requirements": gate["requirements"],
    }
    _write_result(
        workdir,
        _envelope(status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


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
    """Assemble the lean simulation result.json. exit 0 = result.json written (pass or fail);
    exit 2 = BLOCKED, any internal raise, never conflated with status=fail. The --phase final
    argument precondition is checked in __main__.py, which maps it to exit 2 before calling
    here."""
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    if (phase != "final" and not fail_reason) or (
        fail_reason is not None and not fail_reason.strip()
    ):
        print("[sim finalize] BLOCKED: empty --fail-reason", file=sys.stderr)
        return 2
    try:
        return build_result(
            workdir,
            phase=phase,
            scaffold=scaffold,
            requirements=requirements,
            check_review=check_review,
            fail_reason=fail_reason,
            fix_owner=fix_owner,
        )
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[sim finalize] BLOCKED: {exc}", file=sys.stderr)
        return 2
