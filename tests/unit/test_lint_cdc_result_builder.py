"""Unit tests for lint_cdc_result_builder — thin combiner for lint-cdc result.json.

TDD order: Task 1 (AND gate + shape), Task 2 (header derivations),
Task 3 (artifacts[]), Task 4 (golden + schema).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "lint-cdc" / "scripts"))
import lint_cdc_result_builder as rb  # noqa: E402, I001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_workdir(tmp_path, lint_err=0, cdc_err=0):
    wd = tmp_path
    (wd / "lint-violations.json").write_text(
        json.dumps(
            {
                "kind": "lint",
                "counts": {"error": lint_err, "warning": 2, "info": 5},
                "violations": [],
            }
        )
    )
    (wd / "cdc-violations.json").write_text(
        json.dumps(
            {
                "kind": "cdc",
                "counts": {"error": cdc_err, "warning": 0, "info": 14},
                "violations": [],
            }
        )
    )
    (wd / "lint-report.txt").write_text(
        "=== IPD lint-report (SpyGlass) ===\n"
        "top:  tpu_top\n"
        "#     SpyGlass Version : SpyGlass_vL-2016.06\n"
    )
    (wd / "cdc-report.txt").write_text("=== IPD cdc-report (SpyGlass) ===\n")
    (wd / "scripts").mkdir()
    (wd / "scripts" / "constraints.sgdc").write_text("current_design tpu_top\n")
    return wd


# ---------------------------------------------------------------------------
# Task 1: AND gate + lean shape
# ---------------------------------------------------------------------------


def test_envelope_pass_lean_shape(tmp_path):
    wd = _clean_workdir(tmp_path)
    assert rb.run(wd, module="tpu_top", top="tpu_top") == 0
    env = json.loads((wd / "result.json").read_text())
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "lint-cdc",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["top_module"] == "tpu_top"
    assert ss["tool"] == "SpyGlass vL-2016.06"
    assert ss["lint_counts"] == {"error": 0, "warning": 2, "info": 5}
    assert ss["cdc_counts"] == {"error": 0, "warning": 0, "info": 14}
    assert ss["violations"] == []
    # lean: dropped fields absent
    for k in ("note", "waivers", "sgdc_seed"):
        assert k not in ss


def test_envelope_fail_on_lint_error(tmp_path):
    wd = _clean_workdir(tmp_path, lint_err=1)
    # one error-severity lint violation present, carrying the tool message the reason derives from
    (wd / "lint-violations.json").write_text(
        json.dumps(
            {
                "kind": "lint",
                "counts": {"error": 1, "warning": 0, "info": 0},
                "violations": [
                    {
                        "id": "W123:foo.v:9",
                        "rule": "W123",
                        "severity": "error",
                        "file": "foo.v",
                        "line": 9,
                        "message": "inferred latch on signal q",
                    }
                ],
            }
        )
    )
    assert rb.run(wd, module="tpu_top", top="tpu_top") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    ss = env["stage_specific"]
    assert ss["fail_reason"]
    v = ss["violations"][0]
    # reason is derived from the tool message: "<rule>: <message>"
    assert (v["id"], v["severity"], v["reason"]) == (
        "W123:foo.v:9",
        "error",
        "W123: inferred latch on signal q",
    )


# ---------------------------------------------------------------------------
# Task 2: Reproducibility-header derivations
# ---------------------------------------------------------------------------


def test_parse_tool_from_lint_report(tmp_path):
    (tmp_path / "lint-report.txt").write_text(
        "=== IPD lint-report (SpyGlass) ===\n"
        "#     SpyGlass Version : SpyGlass_vL-2016.06\n"
    )
    assert rb.parse_tool(tmp_path) == "SpyGlass vL-2016.06"
    (tmp_path / "lint-report.txt").write_text("no version line\n")
    assert rb.parse_tool(tmp_path) == "SpyGlass unknown"


def test_read_top_from_report_header(tmp_path):
    (tmp_path / "lint-report.txt").write_text("top:  tpu_top\n")
    assert rb.read_top(tmp_path) == "tpu_top"


def test_read_top_from_env_sh_fallback(tmp_path):
    (tmp_path / "env.sh").write_text('TOP="${TOP:-tpu_top}"\n')
    assert rb.read_top(tmp_path) == "tpu_top"


# ---------------------------------------------------------------------------
# Task 3: artifacts[] enumeration
# ---------------------------------------------------------------------------


def test_enumerate_artifacts_present_only_no_self(tmp_path):
    (tmp_path / "scripts").mkdir()
    for rel in [
        "scripts/constraints.sgdc",
        "lint-report.txt",
        "cdc-report.txt",
        "lint-violations.json",
        "cdc-violations.json",
    ]:
        (tmp_path / rel).write_text("x")
    (tmp_path / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in rb.enumerate_artifacts(tmp_path)]
    assert "scripts/constraints.sgdc" in paths  # Iron Rule: warm-start anchor
    assert "lint-violations.json" in paths and "cdc-report.txt" in paths
    assert "result.json" not in paths
    assert all((tmp_path / p).is_file() for p in paths)  # present files only


# ---------------------------------------------------------------------------
# Task 4: Golden test against the real tpu_top run + schema validation
# ---------------------------------------------------------------------------

FIX = Path(__file__).resolve().parent / "fixtures" / "lint-cdc-tpu_top"


def test_golden_lean_against_real_tpu_top(tmp_path):
    wd = tmp_path / "lint-cdc"
    shutil.copytree(FIX, wd)
    assert rb.run(wd, module="tpu_top", top=None) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    # contract / header fields — exact to the real run
    assert env["status"] == "pass"
    assert ss["top_module"] == "tpu_top"  # from the report header, derived
    assert ss["tool"] == "SpyGlass vL-2016.06"
    assert ss["lint_counts"] == {"error": 0, "warning": 2, "info": 5}
    assert ss["cdc_counts"] == {"error": 0, "warning": 0, "info": 14}
    assert ss["violations"] == []  # no error-severity rows -> empty, no reason derived
    # lean: dropped fields ABSENT
    for k in ("note", "waivers", "sgdc_seed"):
        assert k not in ss
    # artifacts present + no self-listing; produced_at normalized
    paths = [a["path"] for a in env["artifacts"]]
    assert "scripts/constraints.sgdc" in paths and "lint-violations.json" in paths
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")


def test_golden_is_schema_valid(tmp_path):
    # Reuse framework.scripts.state.validate_result (Draft202012Validator + Registry).
    # It reads asic/<module>/Design/lint-cdc/result.json relative to cwd, so build
    # into that layout + chdir.
    from framework.scripts import state

    wd = tmp_path / "asic" / "tpu_top" / "Design" / "lint-cdc"
    shutil.copytree(FIX, wd)
    rb.run(wd, module="tpu_top", top=None)
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        valid, err = state.validate_result("tpu_top", "lint-cdc")
    finally:
        os.chdir(old_cwd)
    assert valid, f"golden lint-cdc result.json is not schema-valid: {err}"


def test_fail_envelope_is_schema_valid(tmp_path):
    # The FAIL path must also be schema-valid (the result schema requires fail_reason
    # on fail). Guard the fail shape explicitly.
    from framework.scripts import state

    wd = tmp_path / "asic" / "tpu_top" / "Design" / "lint-cdc"
    shutil.copytree(FIX, wd)
    # inject one error-severity lint violation -> status=fail with fail_reason + violations
    (wd / "lint-violations.json").write_text(
        json.dumps(
            {
                "kind": "lint",
                "counts": {"error": 1, "warning": 0, "info": 0},
                "violations": [
                    {
                        "id": "W123:foo.v:9",
                        "rule": "W123",
                        "severity": "error",
                        "file": "foo.v",
                        "line": 9,
                        "message": "inferred latch on signal q",
                    }
                ],
            }
        )
    )
    assert rb.run(wd, module="tpu_top", top=None) == 0
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        valid, err = state.validate_result("tpu_top", "lint-cdc")
    finally:
        os.chdir(old_cwd)
    assert valid, f"fail-path lint-cdc result.json is not schema-valid: {err}"
    assert json.loads((wd / "result.json").read_text())["status"] == "fail"
