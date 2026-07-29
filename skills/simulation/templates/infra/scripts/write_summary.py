#!/usr/bin/env python3
"""Generate case-results.json plus its two rendered views.

Goal: stable PASS / FAIL / MANUAL_REVIEW / NOT_RUN per testcase.
Coverage closure and full traceability are preserved in the output but are NOT
blocking gates.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Valid result tokens in regression-log.txt RESULT lines.
VALID_STATUSES = {"PASS", "FAIL", "MANUAL_REVIEW"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate simulation summary artifacts."
    )
    parser.add_argument(
        "--verification-dir", required=True, help="Verification directory root."
    )
    parser.add_argument(
        "--coverage-only", action="store_true", help="Only write coverage-summary.txt."
    )
    return parser.parse_args()


def load_results(log_path):
    """Parse regression-log.txt and return list of result dicts.

    Stable RESULT line format (see run_vcs_regression.sh):
        RESULT <test_id> <PASS|FAIL|MANUAL_REVIEW> [...]

    The feature a test traces to is NOT on this line: it is in testlist.json, keyed by the same
    test_id, and carrying it through bash would be a second copy nothing compares.
    """
    if not log_path.is_file():
        sys.exit(
            f"write_summary: missing {log_path}; run `make smoke` or `make regress` first"
        )
    results = []
    pattern = re.compile(r"^RESULT\s+(\S+)\s+(PASS|FAIL|MANUAL_REVIEW)(?:\s+.*)?$")
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            results.append({"test_id": match.group(1), "status": match.group(2)})
    return results


def write_text(path, content):
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main():
    args = parse_args()
    root = Path(args.verification_dir).resolve()
    testlist_path = root / "tests" / "testlist.json"
    log_path = root / "regression-log.txt"
    counts_path = root / "case-results.json"
    coverage_path = root / "coverage-summary.txt"
    summary_path = root / "case-results-summary.md"

    if not testlist_path.is_file():
        sys.exit(
            f"write_summary: missing {testlist_path}; "
            "run sim bootstrap --plan <simulation-plan workdir> first to generate the scaffold"
        )

    testlist = json.loads(testlist_path.read_text(encoding="utf-8"))
    results = load_results(log_path)
    result_by_test = {item["test_id"]: item for item in results}

    tests = testlist.get("tests", [])
    # test_by_id is how a RESULT line reaches its feature: the log carries only test_id.
    test_by_id = {}
    feature_to_tests = defaultdict(list)
    for test in tests:
        test_by_id[test["test_id"]] = test
        feature_to_tests[test["feature_id"]].append(test)

    # Counts — MANUAL_REVIEW is treated as "executed but needs human review".
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    manual_review = sum(1 for r in results if r["status"] == "MANUAL_REVIEW")
    not_run = sum(1 for t in tests if t["test_id"] not in result_by_test)

    executed_pass_features = {
        test_by_id[r["test_id"]]["feature_id"]
        for r in results
        if r["status"] == "PASS" and r["test_id"] in test_by_id
    }
    total_features = len(feature_to_tests)
    feature_coverage = (
        0.0
        if total_features == 0
        else 100.0 * len(executed_pass_features) / total_features
    )
    testcase_pass_rate = 0.0 if total == 0 else 100.0 * passed / total

    # -----------------------------------------------------------------------
    # case-results.json + coverage-summary.txt
    # -----------------------------------------------------------------------
    counts = {
        "total_tests": total,
        "passed_tests": passed,
        "failed_tests": failed,
        "manual_review_tests": manual_review,
        "not_run_tests": not_run,
        "feature_coverage_percent": round(feature_coverage, 1),
        "testcase_pass_rate_percent": round(testcase_pass_rate, 1),
    }
    # case-results.json is the structured home; the two summaries below are rendered views of
    # it for a human. `sim finalize` reads this rather than re-parsing the rendered text.
    counts_path.write_text(
        json.dumps(counts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_text(
        coverage_path,
        "suite_summary\n" + "".join(f"{k}: {v}\n" for k, v in counts.items()),
    )

    if args.coverage_only:
        return 0

    # -----------------------------------------------------------------------
    # case-results-summary.md
    # -----------------------------------------------------------------------
    # Core traceability table (minimum: testcase + feature + result).
    trace_rows = []
    for test in tests:
        result = result_by_test.get(test["test_id"])
        if result:
            status = result["status"]
        else:
            status = "NOT_RUN"
        trace_rows.append(
            f"| {test['feature_id']} | {test['feature_name']} "
            f"| {test['test_id']} | {','.join(test['suites'])} | **{status}** |"
        )
    trace_table = "\n".join(trace_rows) or "| n/a | n/a | n/a | n/a | n/a |"

    # Failed / MANUAL_REVIEW detail table.
    action_rows = []
    for item in results:
        if item["status"] in ("FAIL", "MANUAL_REVIEW"):
            action = "Fix" if item["status"] == "FAIL" else "Review"
            fid = test_by_id.get(item["test_id"], {}).get("feature_id", "-")
            action_rows.append(
                f"| {item['test_id']} | {fid} | {item['status']} "
                f"| {action}; see run_logs/{item['test_id']}.log |"
            )
    for test in tests:
        if test["test_id"] not in result_by_test:
            action_rows.append(
                f"| {test['test_id']} | {test['feature_id']} | NOT_RUN "
                f"| Recompile and re-run |"
            )
    action_table = "\n".join(action_rows) or "| - | - | - | - |"

    # Overall verdict line.
    if failed == 0 and manual_review == 0 and not_run == 0:
        verdict_line = "> **ALL PASS** — ready for human review."
    else:
        issues = []
        if failed:
            issues.append(f"FAIL={failed}")
        if manual_review:
            issues.append(f"MANUAL_REVIEW={manual_review}")
        if not_run:
            issues.append(f"NOT_RUN={not_run}")
        verdict_line = f"> **Attention required**: {', '.join(issues)}."

    summary_text = f"""# Case Results Summary

## Run Context

- Module: `{testlist.get("module", "unknown")}`
- Top: `{testlist.get("top", "unknown")}`
- design.md: `{testlist.get("design", "unknown")}`
- Regression log: `regression-log.txt`
- Coverage summary: `coverage-summary.txt`

## Overall Status

{verdict_line}

| Metric | Value |
|--------|-------|
| Total executed | {total} |
| PASS | {passed} |
| FAIL | {failed} |
| MANUAL_REVIEW | {manual_review} |
| NOT_RUN | {not_run} |
| Feature coverage | {feature_coverage:.1f}% |
| Testcase pass rate | {testcase_pass_rate:.1f}% |

## Feature Traceability

| FeatureID | Feature | Testcase | Suites | Result |
|-----------|---------|----------|--------|--------|
{trace_table}

## Action Items

| Testcase | FeatureID | Status | Action |
|----------|-----------|--------|--------|
{action_table}

## Status Legend

- `PASS`: testbench reported no UVM_FATAL or UVM_ERROR.
- `FAIL`: errors reported; investigate per-test log in `run_logs/`.
- `MANUAL_REVIEW`: status flagged for human inspection.
- `NOT_RUN`: testcase declared but no result line present (likely a compile or selection issue).
"""
    write_text(summary_path, summary_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
