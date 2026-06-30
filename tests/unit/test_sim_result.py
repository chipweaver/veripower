# tests/unit/test_sim_result.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"
DEFAULTS = ROOT / "skills/simulation/defaults.yaml"

SCAFFOLD = {
    "module": "m",
    "top": "m_top",
    "agents": [{"name": "drv", "mode": "active"}, {"name": "obs", "mode": "passive"}],
    "sequences": [{"name": "smoke", "agent": "drv"}],
    "tests": [{"name": "t_smoke", "seqs": ["smoke"]}],
}
COV_PASS = {"aggregate": {"line": 92.0, "cond": 70.0, "fsm": 80.0, "toggle": 85.0}}


def _final_workdir(tmp_path):
    wd = tmp_path
    (wd / "tb/uvm/seq").mkdir(parents=True)
    (wd / "tb/uvm/agent").mkdir(parents=True)
    (wd / "tb/uvm/seq/m_smoke_seq.sv").write_text("class m_smoke_seq; endclass\n")
    for f in (
        "m_drv_driver.sv",
        "m_drv_monitor.sv",
        "m_drv_agent.sv",
        "m_obs_monitor.sv",
        "m_obs_agent.sv",
    ):
        (wd / "tb/uvm/agent" / f).write_text("class x; endclass\n")
    (wd / "scaffold-specification.json").write_text(json.dumps(SCAFFOLD))
    (wd / "structural-coverage.json").write_text(json.dumps(COV_PASS))
    (wd / "coverage-summary.txt").write_text(
        "total_tests: 3\npassed_tests: 3\nfailed_tests: 0\n"
    )
    return wd


def _finalize(wd, *extra):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--module",
            "m",
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def test_final_pass_writes_result(tmp_path):
    wd = _final_workdir(tmp_path)
    proc = _finalize(
        wd,
        "--phase",
        "final",
        "--scaffold",
        str(wd / "scaffold-specification.json"),
        "--thresholds",
        str(DEFAULTS),
    )
    assert proc.returncode == 0, proc.stderr
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "simulation" and env["status"] == "pass"
    assert env["stage_specific"]["total_cases"] == 3
    assert "result.json" not in [a["path"] for a in env["artifacts"]]


def test_verify_handoff_promoted(tmp_path):
    # TB-freeze §7 decision A: verify-handoff.json is promoted to artifacts[] so the
    # freeze classifier can locate it via the canonical result's artifact list.
    wd = _final_workdir(tmp_path)
    (wd / "verify-handoff.json").write_text("{}\n")
    (wd / "conformance-review.json").write_text('{"findings": []}\n')
    proc = _finalize(
        wd,
        "--phase",
        "final",
        "--scaffold",
        str(wd / "scaffold-specification.json"),
        "--thresholds",
        str(DEFAULTS),
    )
    assert proc.returncode == 0, proc.stderr
    paths = [
        a["path"] for a in json.loads((wd / "result.json").read_text())["artifacts"]
    ]
    assert "verify-handoff.json" in paths
    assert "conformance-review.json" in paths  # a sibling handoff IS also promoted


def test_final_pass_missing_summary_is_blocked(tmp_path):
    # S4: a missing coverage-summary.txt on the pass path is a broken pipeline step;
    # finalize must fail loud (exit 2 BLOCKED), not write null counts.
    wd = _final_workdir(tmp_path)
    (wd / "coverage-summary.txt").unlink()
    proc = _finalize(
        wd,
        "--phase",
        "final",
        "--scaffold",
        str(wd / "scaffold-specification.json"),
        "--thresholds",
        str(DEFAULTS),
    )
    assert proc.returncode == 2, proc.stdout
    assert not (wd / "result.json").exists()


def test_conformance_phase_requires_review_file(tmp_path):
    # S5: --phase conformance is only reached on a gate=trip, where the main thread
    # has assembled conformance-review.json; an absent file is a caller contract
    # violation that must fail loud (exit 2), not silently write empty findings.
    proc = _finalize(
        tmp_path,
        "--phase",
        "conformance",
        "--fail-reason",
        "tp X missing check",
    )
    assert proc.returncode == 2, proc.stdout
    assert not (tmp_path / "result.json").exists()


def test_final_thin_fail_is_compile(tmp_path):
    wd = _final_workdir(tmp_path)
    (wd / "tb/uvm/agent/m_drv_driver.sv").write_text("// TODO(driver)\n")  # residue
    proc = _finalize(
        wd,
        "--phase",
        "final",
        "--scaffold",
        str(wd / "scaffold-specification.json"),
        "--thresholds",
        str(DEFAULTS),
    )
    assert proc.returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert (
        env["status"] == "fail" and env["stage_specific"]["failure_phase"] == "compile"
    )


def test_final_coverage_fail(tmp_path):
    wd = _final_workdir(tmp_path)
    (wd / "structural-coverage.json").write_text(
        json.dumps(
            {"aggregate": {"line": 10.0, "cond": 70.0, "fsm": 80.0, "toggle": 85.0}}
        )
    )
    proc = _finalize(
        wd,
        "--phase",
        "final",
        "--scaffold",
        str(wd / "scaffold-specification.json"),
        "--thresholds",
        str(DEFAULTS),
    )
    assert (
        proc.returncode == 0
    )  # a coverage fail still writes result.json (exit 0, not BLOCKED)
    env = json.loads((wd / "result.json").read_text())
    assert (
        env["status"] == "fail" and env["stage_specific"]["failure_phase"] == "coverage"
    )


def test_early_exit_smoke(tmp_path):
    wd = tmp_path
    proc = _finalize(
        wd,
        "--phase",
        "smoke",
        "--failure-phase",
        "smoke",
        "--fail-reason",
        "case X failed",
    )
    assert proc.returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail" and env["stage_specific"]["failure_phase"] == "smoke"
    assert env["stage_specific"]["fail_reason"] == "case X failed"


def test_final_requires_scaffold_thresholds_exit_2(tmp_path):
    proc = _finalize(tmp_path, "--phase", "final")  # missing --scaffold/--thresholds
    assert proc.returncode == 2
    assert not (tmp_path / "result.json").exists()


def test_finalize_blocked_exit_2(tmp_path):
    # --phase final with a non-existent scaffold path -> build_result raises -> exit 2 (BLOCKED)
    proc = _finalize(
        tmp_path,
        "--phase",
        "final",
        "--scaffold",
        str(tmp_path / "nope.json"),
        "--thresholds",
        str(DEFAULTS),
    )
    assert proc.returncode == 2


def test_final_pass_writes_plan_digest(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "skills/simulation/scripts"))
    from sim import classify

    wd = _final_workdir(tmp_path)
    plan = wd / "verification-plan.md"
    plan.write_text("# plan\n")
    proc = _finalize(
        wd,
        "--phase",
        "final",
        "--scaffold",
        str(wd / "scaffold-specification.json"),
        "--thresholds",
        str(DEFAULTS),
        "--plan",
        str(plan),
    )
    assert proc.returncode == 0, proc.stderr
    env = json.loads((wd / "result.json").read_text())
    assert env["stage_specific"]["plan_digest"] == classify.plan_digest(
        wd / "scaffold-specification.json", plan
    )


def test_regress_fail_writes_plan_digest(tmp_path):
    import sys

    sys.path.insert(0, str(ROOT / "skills/simulation/scripts"))
    from sim import classify

    wd = tmp_path
    (wd / "scaffold-specification.json").write_text(json.dumps(SCAFFOLD))
    plan = wd / "verification-plan.md"
    plan.write_text("# plan\n")
    proc = _finalize(
        wd,
        "--phase",
        "regress",
        "--failure-phase",
        "regress",
        "--fail-reason",
        "case X failed",
        "--scaffold",
        str(wd / "scaffold-specification.json"),
        "--plan",
        str(plan),
    )
    assert proc.returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert (
        env["status"] == "fail" and env["stage_specific"]["failure_phase"] == "regress"
    )
    assert env["stage_specific"]["plan_digest"] == classify.plan_digest(
        wd / "scaffold-specification.json", plan
    )
