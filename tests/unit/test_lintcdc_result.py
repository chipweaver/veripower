"""Unit tests for lintcdc.result — thin combiner for lint-cdc result.json.

TDD order: Task 1 (AND gate + shape), Task 2 (header derivations),
Task 3 (artifacts[]), Task 4 (golden + schema).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "lint-cdc" / "scripts"))
from lintcdc import result as rb  # noqa: E402, I001


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
    assert rb.run(wd, module="tpu_top") == 0
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["module"]) == (
        "lint-cdc",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["tool"] == "SpyGlass vL-2016.06"
    assert ss["violations"] == []
    # lean: dropped fields absent
    for k in (
        "note",
        "waivers",
        "sgdc_seed",
        "top_module",
        "lint_counts",
        "cdc_counts",
    ):
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
    assert rb.run(wd, module="tpu_top") == 0
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
    assert rb.run(wd, module="tpu_top") == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    # contract / header fields — exact to the real run
    assert env["status"] == "pass"
    assert ss["tool"] == "SpyGlass vL-2016.06"
    assert ss["violations"] == []  # no error-severity rows -> empty, no reason derived
    # lean: dropped fields ABSENT
    for k in (
        "note",
        "waivers",
        "sgdc_seed",
        "top_module",
        "lint_counts",
        "cdc_counts",
    ):
        assert k not in ss
    # artifacts present + no self-listing; produced_at normalized
    paths = [a["path"] for a in env["artifacts"]]
    assert "scripts/constraints.sgdc" in paths and "lint-violations.json" in paths
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")


def test_golden_is_schema_valid(tmp_path):
    # Reuse framework.scripts.facts.validate_result (Draft202012Validator + Registry)
    # on the produced result.json dict.
    from framework.scripts import facts

    wd = tmp_path / "asic" / "tpu_top" / "Design" / "lint-cdc"
    shutil.copytree(FIX, wd)
    rb.run(wd, module="tpu_top")
    result = json.loads((wd / "result.json").read_text())
    err = facts.validate_result("lint-cdc", result)
    assert err is None, f"golden lint-cdc result.json is not schema-valid: {err}"


def test_fail_envelope_is_schema_valid(tmp_path):
    # The FAIL path must also be schema-valid (the result schema requires fail_reason
    # on fail). Guard the fail shape explicitly.
    from framework.scripts import facts

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
    assert rb.run(wd, module="tpu_top") == 0
    result = json.loads((wd / "result.json").read_text())
    err = facts.validate_result("lint-cdc", result)
    assert err is None, f"fail-path lint-cdc result.json is not schema-valid: {err}"
    assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# Attribution: fix_owner is the one field this verb cannot derive. Everything the
# report says is already in violations[]; whose artifact must change is not.
# ---------------------------------------------------------------------------


def test_fail_envelope_carries_the_agent_named_fix_owner(tmp_path):
    """fix_owner is the one field this verb cannot derive: a constraint-family violation is
    reported at an RTL line while the fix belongs in the SGDC, and no rule prefix adjudicates
    that. The agent names it; finalize only records it."""
    wd = _clean_workdir(tmp_path, cdc_err=1)
    (wd / "cdc-violations.json").write_text(
        json.dumps(
            {
                "kind": "cdc",
                "counts": {"error": 1, "warning": 0, "info": 0},
                "violations": [
                    {
                        "id": "Clock_info05:cdc_smoke.clk2",
                        "rule": "Clock_info05",
                        "severity": "error",
                        "message": "Clock-Net is unconstrained",
                    }
                ],
            }
        )
    )
    assert rb.run(wd, module="tpu_top", fix_owner="specification") == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fix_owner"] == "specification"


def test_fail_envelope_omits_fix_owner_when_unnamed(tmp_path):
    """Absence is the signal decide reads as "this stage cannot tell", so an unnamed owner
    must not serialize as a present-but-empty key."""
    wd = _clean_workdir(tmp_path, cdc_err=1)
    assert rb.run(wd, module="tpu_top") == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert "fix_owner" not in ss


def test_fail_envelope_no_violations_omits_failures(tmp_path):
    # Report-missing early-fail path: no error-severity violation rows at all ->
    # nothing to classify -> failures[] stays unset (not invented).
    wd = _clean_workdir(tmp_path)
    (wd / "lint-violations.json").unlink()
    assert rb.run(wd, module="tpu_top") == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert "failures" not in ss


# ---------------------------------------------------------------------------
# New: finalize() wrapper (BLOCKED policy) + CLI dispatch
# ---------------------------------------------------------------------------


def test_early_fail_reason_wins_and_is_the_failure_declaration(tmp_path):
    """The Step 4/5 early-fail closes through this verb too. `make` died before the parser
    wrote its sidecar, so the cause exists only on stderr where the agent read it; passing it
    is what declares the failure, and it must not be overwritten by the derived gate wording."""
    wd = _clean_workdir(tmp_path)
    (wd / "cdc-violations.json").unlink()  # write-fresh-or-nothing removed it
    reason = "SpyGlass exited 1 before cdc_setup: no license for cdc/cdc_verify_struct"
    assert rb.run(wd, module="tpu_top", fail_reason=reason, fix_owner="rtl-design") == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert ss["fail_reason"] == reason  # not "CDC report missing/unparseable, ..."
    assert ss["fix_owner"] == "rtl-design"


def test_fail_reason_forces_fail_on_an_otherwise_clean_pair(tmp_path):
    # A tool failure can leave both sidecars clean (e.g. make died after reporting).
    # Supplying the reason is the failure declaration, so the gate must not out-vote it.
    wd = _clean_workdir(tmp_path)
    assert rb.run(wd, module="tpu_top", fail_reason="spyglass crashed post-report") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["fail_reason"] == "spyglass crashed post-report"


def test_empty_fail_reason_is_blocked_not_a_fail(tmp_path):
    # An unreasoned early-fail is a program error, never a routable verdict.
    wd = _clean_workdir(tmp_path)
    assert rb.finalize(wd, "tpu_top", None, "   ") == 2
    assert not (wd / "result.json").exists()


def test_unreasoned_waiver_is_blocked(tmp_path):
    """A waiver is the only route from a real error to pass, and SpyGlass subtracts it before
    the parser counts, so the envelope cannot distinguish a waived error from one that never
    happened. An entry with no rationale must not be able to close the stage."""
    wd = _clean_workdir(tmp_path)
    (wd / "scripts").mkdir(exist_ok=True)
    (wd / "scripts" / "waiver.tcl").write_text(
        "# a real rule id, no reason given\nwaive -rules {W257}\n"
    )
    assert rb.finalize(wd, "tpu_top") == 2
    assert not (wd / "result.json").exists()


def test_empty_comment_waiver_is_blocked(tmp_path):
    wd = _clean_workdir(tmp_path)
    (wd / "scripts").mkdir(exist_ok=True)
    (wd / "scripts" / "waiver.tcl").write_text('waive -rules {W257} -comment "   "\n')
    assert rb.finalize(wd, "tpu_top") == 2


def test_reasoned_waiver_passes_across_continuations_and_comments(tmp_path):
    """The real shape: commented-out examples must not register as entries, and a live entry
    is spread over backslash-continued lines with the -comment on the last one."""
    wd = _clean_workdir(tmp_path)
    (wd / "scripts").mkdir(exist_ok=True)
    (wd / "scripts" / "waiver.tcl").write_text(
        "# waive -rules {W391} \\\n"
        '#       -comment "an example, not an entry"\n'
        "set_option mthresh 8192\n"
        "waive -rules {W257} \\\n"
        "      -file {foo.v} \\\n"
        '      -comment "synthesis ignores the delay; simulation-only model"\n'
    )
    assert rb.finalize(wd, "tpu_top") == 0
    assert json.loads((wd / "result.json").read_text())["status"] == "pass"


def test_shipped_waiver_template_satisfies_its_own_backstop(tmp_path):
    """The deployed template must not itself be BLOCKED — its examples are commented out."""
    wd = _clean_workdir(tmp_path)
    (wd / "scripts").mkdir(exist_ok=True)
    shutil.copy(
        REPO_ROOT / "skills/lint-cdc/templates/scripts/waiver.tcl",
        wd / "scripts" / "waiver.tcl",
    )
    assert rb.waiver_defects(wd) == []


def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps run(): any internal raise -> exit 2 (BLOCKED), never
    # status=fail. (The deleted main() owned this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(rb, "run", boom)
    assert rb.finalize(tmp_path, "tpu_top") == 2


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    MAIN = REPO_ROOT / "skills/lint-cdc/scripts/lintcdc/__main__.py"
    # missing --module -> argparse exit 2
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --module
    # missing --workdir -> argparse exit 2
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--module", "tpu_top"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --workdir


def test_finalize_cli_happy_path(tmp_path):
    # End-to-end through _cmd_finalize (lazy handler import + arg mapping), not just
    # in-process run(). A handler typo would pass every other test (which call run()
    # directly) but fail here. --top omitted -> defaults to the report header.
    wd = _clean_workdir(tmp_path)
    MAIN = REPO_ROOT / "skills/lint-cdc/scripts/lintcdc/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--module",
            "tpu_top",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"], env["module"]) == (
        "lint-cdc",
        "pass",
        "tpu_top",
    )
