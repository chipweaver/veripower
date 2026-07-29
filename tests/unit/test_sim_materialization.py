# tests/unit/test_sim_materialization.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"

SCAFFOLD = {
    "module": "m",
    "agents": [{"name": "drv", "mode": "active"}, {"name": "obs", "mode": "passive"}],
    "sequences": [{"name": "smoke", "agent": "drv"}],
}


def _workdir(tmp_path, todo=False):
    (tmp_path / "tb/uvm/seq").mkdir(parents=True)
    (tmp_path / "tb/uvm/agent").mkdir(parents=True)
    (tmp_path / "tb/uvm/seq/m_smoke_seq.sv").write_text("class m_smoke_seq; endclass\n")
    body = "// TODO(driver): fill\n" if todo else "class m_drv_driver; endclass\n"
    (tmp_path / "tb/uvm/agent/m_drv_driver.sv").write_text(body)
    for f in (
        "m_drv_monitor.sv",
        "m_drv_agent.sv",
        "m_obs_monitor.sv",
        "m_obs_agent.sv",
    ):
        (tmp_path / "tb/uvm/agent" / f).write_text("class x; endclass\n")
    doc = dict(SCAFFOLD)
    (tmp_path / "sequences.json").write_text(json.dumps(doc.pop("sequences", [])))
    (tmp_path / "tb-scaffold.json").write_text(json.dumps(doc))
    return tmp_path, tmp_path


def _run(wd, sp):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-materialization",
            "--workdir",
            str(wd),
            "--plan",
            str(sp),
        ],
        capture_output=True,
        text=True,
    )


def test_materialization_clean_exit_0(tmp_path):
    wd, sp = _workdir(tmp_path)
    r = _run(wd, sp)
    assert r.returncode == 0, r.stderr
    # gate-class: stdout is EXACTLY one verdict JSON line (json.loads on the whole stdout, not
    # splitlines()[-1] — a stray human line would now make this raise, catching the contract breach).
    assert json.loads(r.stdout) == {"unmaterialized": [], "todo_residue": []}


def test_materialization_todo_exit_1_stderr(tmp_path):
    wd, sp = _workdir(tmp_path, todo=True)
    r = _run(wd, sp)
    assert r.returncode == 1
    verdict = json.loads(r.stdout)  # still exactly one JSON line on the fail path
    assert verdict["todo_residue"]  # non-empty
    assert "materialization incomplete" in r.stderr
