# tests/unit/test_infra_summary.py
"""The deployed regression-summary chain: select_tests.py and write_summary.py.

Both are templates deployed into a simulation workdir, so nothing else in the suite executes
them. These do.

The last test is the point of the file: `run_vcs_regression.sh` writes the RESULT line and
write_summary.py parses it, across a language boundary, and the shell's own header says "DO NOT
change the token order or keyword names without also updating write_summary.py". That invariant
was comment-maintained; here the line is DERIVED from the shell source and fed to the parser.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "skills/simulation/templates/infra/scripts"
SELECT = INFRA / "select_tests.py"
SUMMARY = INFRA / "write_summary.py"
REGRESS = INFRA / "run_vcs_regression.sh"

_TESTS = [
    {
        "test_id": "T-01",
        "uvm_testname": "m_smoke_test",
        "feature_id": "F-01",
        "feature_name": "Register write path",
        "suites": ["smoke", "regress"],
        "seqs": [],
    },
    {
        "test_id": "T-02",
        "uvm_testname": "m_corner_test",
        "feature_id": "F-02",
        "feature_name": "FIFO occupancy flags",
        "suites": ["regress"],
        "seqs": [],
    },
]


def _workdir(tmp_path, results):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "testlist.json").write_text(
        json.dumps({"module": "m", "top": "m_top", "tests": _TESTS})
    )
    (tmp_path / "regression-log.txt").write_text("".join(f"{r}\n" for r in results))
    return tmp_path


def _run_summary(wd, *extra):
    return subprocess.run(
        [sys.executable, str(SUMMARY), "--verification-dir", str(wd), *extra],
        capture_output=True,
        text=True,
    )


# ── select_tests.py ───────────────────────────────────────────────────────────
def _select(wd, mode, requested="-"):
    return subprocess.run(
        [sys.executable, str(SELECT), mode, requested, str(wd / "tests/testlist.json")],
        capture_output=True,
        text=True,
    )


def test_select_smoke_picks_only_the_smoke_suite(tmp_path):
    wd = _workdir(tmp_path, [])
    r = _select(wd, "smoke")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["T-01|m_smoke_test"]


def test_select_regress_picks_both(tmp_path):
    wd = _workdir(tmp_path, [])
    assert _select(wd, "regress").stdout.splitlines() == [
        "T-01|m_smoke_test",
        "T-02|m_corner_test",
    ]


def test_select_row_carries_no_feature(tmp_path):
    # The feature is in testlist.json keyed by the same test_id; carrying it through the pipe
    # and back out of a RESULT line would be a second copy nothing compares.
    wd = _workdir(tmp_path, [])
    for row in _select(wd, "regress").stdout.splitlines():
        assert row.count("|") == 1
        assert "F-0" not in row


def test_select_single_matches_either_id_or_uvm_name(tmp_path):
    wd = _workdir(tmp_path, [])
    assert _select(wd, "single", "T-02").stdout.strip() == "T-02|m_corner_test"
    assert _select(wd, "single", "m_corner_test").stdout.strip() == "T-02|m_corner_test"


def test_select_no_match_exits_2(tmp_path):
    wd = _workdir(tmp_path, [])
    assert _select(wd, "single", "ghost").returncode == 2


# ── write_summary.py ──────────────────────────────────────────────────────────
def test_counts_land_in_case_results_json(tmp_path):
    wd = _workdir(
        tmp_path,
        ["RESULT T-01 PASS uvm_testname=m_smoke_test log=logs/T-01.log"],
    )
    r = _run_summary(wd)
    assert r.returncode == 0, r.stderr
    counts = json.loads((wd / "case-results.json").read_text())
    assert counts["total_tests"] == 1
    assert counts["passed_tests"] == 1
    assert counts["not_run_tests"] == 1  # T-02 never ran
    assert counts["feature_coverage_percent"] == 50.0  # 1 of 2 features passed


def test_rendered_views_agree_with_the_json(tmp_path):
    wd = _workdir(
        tmp_path,
        [
            "RESULT T-01 PASS uvm_testname=m_smoke_test log=logs/T-01.log",
            "RESULT T-02 FAIL uvm_testname=m_corner_test log=logs/T-02.log",
        ],
    )
    assert _run_summary(wd).returncode == 0
    counts = json.loads((wd / "case-results.json").read_text())
    cov = (wd / "coverage-summary.txt").read_text()
    for k, v in counts.items():
        assert f"{k}: {v}" in cov, f"coverage-summary.txt disagrees on {k}"
    md = (wd / "case-results-summary.md").read_text()
    assert f"| FAIL | {counts['failed_tests']} |" in md


def test_traceability_shows_the_real_feature_name(tmp_path):
    # The Feature column must not be the FeatureID column again: feature_name comes from
    # features.json via materialize-scaffold, and this is where a human reads it.
    wd = _workdir(
        tmp_path, ["RESULT T-01 PASS uvm_testname=m_smoke_test log=logs/T-01.log"]
    )
    assert _run_summary(wd).returncode == 0
    md = (wd / "case-results-summary.md").read_text()
    assert "| F-01 | Register write path | T-01 | smoke,regress | **PASS** |" in md


def test_action_table_resolves_feature_by_joining_test_id(tmp_path):
    wd = _workdir(
        tmp_path, ["RESULT T-02 FAIL uvm_testname=m_corner_test log=logs/T-02.log"]
    )
    assert _run_summary(wd).returncode == 0
    md = (wd / "case-results-summary.md").read_text()
    assert "| T-02 | F-02 | FAIL |" in md  # feature came from the testlist, not the log


def test_result_line_for_unknown_test_id_does_not_crash(tmp_path):
    # A log line whose test_id is not in the testlist (a stale log across a plan revision)
    # must not take the whole summary down.
    wd = _workdir(
        tmp_path, ["RESULT T-GHOST FAIL uvm_testname=m_ghost_test log=logs/x.log"]
    )
    r = _run_summary(wd)
    assert r.returncode == 0, r.stderr
    assert "| T-GHOST | - | FAIL |" in (wd / "case-results-summary.md").read_text()


def test_coverage_only_skips_the_review_summary(tmp_path):
    wd = _workdir(
        tmp_path, ["RESULT T-01 PASS uvm_testname=m_smoke_test log=logs/T-01.log"]
    )
    assert _run_summary(wd, "--coverage-only").returncode == 0
    assert (wd / "case-results.json").is_file()
    assert (wd / "coverage-summary.txt").is_file()
    assert not (wd / "case-results-summary.md").exists()


def test_missing_regression_log_fails_loud(tmp_path):
    wd = _workdir(tmp_path, [])
    (wd / "regression-log.txt").unlink()
    r = _run_summary(wd)
    assert r.returncode != 0 and "regression-log.txt" in r.stderr


# ── the cross-language RESULT format ──────────────────────────────────────────
def test_shell_result_line_is_parseable_by_the_summary(tmp_path):
    """Derive the RESULT line from run_vcs_regression.sh's own echo and parse it.

    Replaces the shell header's "DO NOT change the token order without also updating
    write_summary.py" with a check: the shell's format string is read here, its variables
    substituted, and the line handed to the real script.
    """
    sh = REGRESS.read_text()
    m = re.search(r'echo "(RESULT [^"]+)" >>"\$regression_log"', sh)
    assert m, (
        "run_vcs_regression.sh no longer echoes a RESULT line in the expected shape"
    )
    line = (
        m.group(1)
        .replace("$test_id", "T-01")
        .replace("$status", "PASS")
        .replace("$uvm_testname", "m_smoke_test")
        .replace("$log_path", "logs/T-01.log")
    )
    assert "$" not in line, f"unsubstituted shell variable in {line!r}"
    wd = _workdir(tmp_path, [line])
    assert _run_summary(wd).returncode == 0
    assert json.loads((wd / "case-results.json").read_text())["passed_tests"] == 1
