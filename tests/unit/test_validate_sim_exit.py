# tests/unit/test_validate_sim_exit.py
"""Tests for validate_sim_exit.py: thin-D1 + D5 + D6 one-pass exit gate."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/simulation/scripts/validate_sim_exit.py"
DEFAULTS = ROOT / "skills/simulation/defaults.yaml"

SCAFFOLD = {
    "module": "m",
    "top": "m_top",
    "agents": [{"name": "drv", "mode": "active"}, {"name": "obs", "mode": "passive"}],
    "sequences": [{"name": "smoke", "agent": "drv"}],
    "tests": [{"name": "t_smoke", "seqs": ["smoke"]}],
}
# Coverage above the Task-1 thresholds (line>=80 cond>=60 fsm>=50 toggle>=70).
COV_PASS = {
    "aggregate": {
        "line": 92.0,
        "cond": 70.0,
        "fsm": 80.0,
        "toggle": 85.0,
        "branch": 90.0,
        "score": 84.0,
    },
    "per_module": [],
}


def _workdir(tmp_path, scaffold=SCAFFOLD, cov=COV_PASS, todo=False, drop_seq=False):
    wd = tmp_path
    (wd / "tb/uvm/seq").mkdir(parents=True)
    (wd / "tb/uvm/agent").mkdir(parents=True)
    if not drop_seq:
        (wd / "tb/uvm/seq/m_smoke_seq.sv").write_text(
            "class m_smoke_seq; task body(); endtask endclass\n"
        )
    # Deploy the infra base class (post-Task-2b: reworded, NO "TODO") to prove the plain-TODO
    # regex does not false-positive on the always-present infra layer in a completed TB.
    (wd / "tb/uvm/seq/base_seq.sv").write_text(
        "class m_base_seq; task body();\n"
        '  `uvm_info(get_type_name(), "NOTE: base body is a no-op; override in subclass.", UVM_LOW)\n'
        "endtask endclass\n"
    )
    body = "// TODO(driver): fill\n" if todo else "class m_drv_driver; endclass\n"
    (wd / "tb/uvm/agent/m_drv_driver.sv").write_text(body)
    (wd / "tb/uvm/agent/m_drv_monitor.sv").write_text("class m_drv_monitor; endclass\n")
    (wd / "tb/uvm/agent/m_drv_agent.sv").write_text("class m_drv_agent; endclass\n")
    (wd / "tb/uvm/agent/m_obs_monitor.sv").write_text("class m_obs_monitor; endclass\n")
    (wd / "tb/uvm/agent/m_obs_agent.sv").write_text("class m_obs_agent; endclass\n")
    (wd / "scaffold-specification.json").write_text(json.dumps(scaffold))
    if cov is not None:
        (wd / "structural-coverage.json").write_text(json.dumps(cov))
    return wd


def _run(wd, check=True):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--workdir",
            str(wd),
            "--scaffold",
            str(wd / "scaffold-specification.json"),
            "--thresholds",
            str(DEFAULTS),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_all_pass(tmp_path):
    proc = _run(_workdir(tmp_path))
    assert proc.returncode == 0 and "OK" in proc.stdout


def test_d6_below_threshold_fails(tmp_path):
    cov = {
        "aggregate": {
            "line": 45.0,
            "cond": 20.0,
            "fsm": 7.0,
            "toggle": 27.0,
            "branch": 33.0,
            "score": 26.0,
        },
        "per_module": [],
    }
    proc = _run(_workdir(tmp_path, cov=cov), check=False)
    assert proc.returncode != 0 and "fsm" in proc.stderr and "line" in proc.stderr
    # the fail path still emits the agent-consumed verdict JSON on stdout (last line)
    verdict = json.loads(proc.stdout.strip().splitlines()[-1])
    assert (
        verdict["coverage_extractable"] is True
    )  # coverage IS extractable; gate failed on value
    assert verdict["dims"]["fsm"]["pass"] is False


def test_d6_skips_absent_dim(tmp_path):
    # datapath DUT: fsm is None (no FSM) -> skip, do not fail on it.
    cov = {
        "aggregate": {
            "line": 92.0,
            "cond": 70.0,
            "fsm": None,
            "toggle": 85.0,
            "branch": 90.0,
            "score": 84.0,
        },
        "per_module": [],
    }
    assert _run(_workdir(tmp_path, cov=cov)).returncode == 0


def test_d5_missing_coverage_fails(tmp_path):
    proc = _run(_workdir(tmp_path, cov=None), check=False)
    assert proc.returncode != 0 and "coverage" in proc.stderr.lower()


def test_d1_todo_residue_fails(tmp_path):
    proc = _run(_workdir(tmp_path, todo=True), check=False)
    assert proc.returncode != 0 and "TODO" in proc.stderr


def test_d1_missing_seq_file_fails(tmp_path):
    proc = _run(_workdir(tmp_path, drop_seq=True), check=False)
    assert proc.returncode != 0 and "m_smoke_seq" in proc.stderr


def test_d1_unreworded_base_seq_todo_fails(tmp_path):
    # Guards Task 2b: an infra base_seq still carrying the old "TODO:" string must fail the
    # plain-TODO gate -- proves the template cleanup is load-bearing, not cosmetic.
    wd = _workdir(tmp_path)
    (wd / "tb/uvm/seq/base_seq.sv").write_text(
        "class m_base_seq; task body();\n"
        '  `uvm_info(get_type_name(), "TODO: drive spec-derived stimulus here.", UVM_LOW)\n'
        "endtask endclass\n"
    )
    proc = _run(wd, check=False)
    assert proc.returncode != 0 and "base_seq" in proc.stderr


def test_d1_todo_in_svh_fails(tmp_path):
    # derive_scaffold emits tb/uvm/test/generated_tests.svh; an unfilled no-seq test leaves
    # "// TODO: Start sequences here." there. The .svh must be scanned, not just .sv.
    wd = _workdir(tmp_path)
    (wd / "tb/uvm/test").mkdir(parents=True)
    (wd / "tb/uvm/test/generated_tests.svh").write_text(
        "// TODO: Start sequences here.\n"
    )
    proc = _run(wd, check=False)
    assert proc.returncode != 0 and "generated_tests.svh" in proc.stderr


def test_verdict_json_on_stdout(tmp_path):
    proc = _run(_workdir(tmp_path))
    # last stdout line is a JSON verdict the agent copies into result.json stage_specific
    verdict = json.loads(proc.stdout.strip().splitlines()[-1])
    assert verdict["coverage_extractable"] is True
    assert verdict["dims"]["fsm"]["pass"] is True
