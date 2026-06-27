# tests/unit/test_sim_scaffold.py
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"
TEMPLATES = ROOT / "skills/simulation/templates/scaffold"
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import scaffold  # noqa: E402

SPEC = {
    "module": "m",
    "top": "m_top",
    "primary_clock": {"dut_port_name": "clk", "period_ns": 10.0},
    "reset": {"dut_port_name": "rst_n"},
    "agents": [
        {
            "name": "drv",
            "mode": "active",
            "interface": {"signals": [{"name": "req", "width": 1}]},
            "transaction": {"fields": [{"name": "data", "width": 8, "rand": True}]},
        },
        {
            "name": "obs",
            "mode": "passive",
            "interface": {"signals": [{"name": "ack", "width": 1}]},
            "transaction": {"fields": [{"name": "resp", "width": 8}]},
        },
    ],
    "sequences": [{"name": "smoke", "agent": "drv"}],
    "tests": [{"name": "t_smoke", "seqs": ["smoke"], "feature": "F-1"}],
    "scoreboard": {"compare_txn": "m_obs_txn"},
    "rm": {"inports": ["m_drv_txn"]},
}


def _write_spec(tmp_path, spec=SPEC):
    p = tmp_path / "scaffold-specification.json"
    p.write_text(json.dumps(spec))
    return p


def _render_via_cli(tmp_path, spec=SPEC):
    spec_path = _write_spec(tmp_path, spec)
    out = tmp_path / "out"
    out.mkdir()
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "render-scaffold",
            "--scaffold",
            str(spec_path),
            "--output-dir",
            str(out),
            "--template-dir",
            str(TEMPLATES),
        ],
        capture_output=True,
        text=True,
    ), out


def test_render_scaffold_full_tree(tmp_path):
    r, out = _render_via_cli(tmp_path)
    assert r.returncode == 0, r.stderr
    # interface / txn / agent / seq / env / scoreboard / rm / tb_top / pkg / filelist / testlist
    assert (out / "tb/uvm/interface/m_drv_if.sv").is_file()
    assert (out / "tb/uvm/transaction/m_drv_txn.sv").is_file()
    assert (out / "tb/uvm/agent/m_drv_driver.sv").is_file()  # active -> driver
    assert (out / "tb/uvm/agent/m_obs_driver.sv").is_file()  # rendered for all agents
    assert (out / "tb/uvm/seq/m_smoke_seq.sv").is_file()
    assert (out / "tb/uvm/top/m_top_tb_top.sv").is_file()
    assert (out / "tests/testlist.json").is_file()


def test_testlist_field_format_and_smoke_budget(tmp_path):
    r, out = _render_via_cli(tmp_path)
    tl = json.loads((out / "tests/testlist.json").read_text())
    assert tl["module"] == "m" and tl["top"] == "m_top"
    entry = tl["tests"][0]
    for k in ("test_id", "uvm_testname", "feature_id", "class", "suites", "seqs"):
        assert k in entry
    assert entry["uvm_testname"] == "m_t_smoke_test"
    assert "smoke" in entry["suites"]  # first 2 tests get smoke


def test_obs_name_strip_wires_rm_and_scoreboard(tmp_path):
    # Cross-stage _obs_name contract: m_drv_txn -> inport "drv"; m_obs_txn -> observer "obs".
    r, out = _render_via_cli(tmp_path)
    assert r.returncode == 0, r.stderr
    rm = (out / "tb/uvm/refmodel/m_rule_rm.sv").read_text()
    assert "write_drv" in rm  # inport agent derived by stripping module_/_txn
    env = (out / "tb/uvm/env/m_env.sv").read_text()
    assert "m_obs_agent.ap.connect(m_scoreboard.analysis_export)" in env  # observer
    assert "m_drv_agent.ap.connect(m_rm.ai_drv)" in env  # inport -> rm


def test_missing_primary_clock_exits(tmp_path):
    spec = {**SPEC}
    del spec["primary_clock"]
    r, _ = _render_via_cli(tmp_path, spec)
    assert r.returncode != 0 and "primary_clock" in r.stderr


def test_nonnumeric_period_exits(tmp_path):
    spec = {**SPEC, "primary_clock": {"dut_port_name": "clk", "period_ns": "fast"}}
    r, _ = _render_via_cli(tmp_path, spec)
    assert r.returncode != 0 and "period_ns" in r.stderr


def test_missing_reset_exits(tmp_path):
    spec = {**SPEC}
    del spec["reset"]
    r, _ = _render_via_cli(tmp_path, spec)
    assert r.returncode != 0 and "reset" in r.stderr


def test_empty_agent_signals_exits(tmp_path):
    spec = json.loads(json.dumps(SPEC))
    spec["agents"][0]["interface"]["signals"] = []
    r, _ = _render_via_cli(tmp_path, spec)
    assert r.returncode != 0 and "interface.signals" in r.stderr


def test_render_missing_scaffold_exits(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "render-scaffold",
            "--scaffold",
            str(tmp_path / "nope.json"),
            "--output-dir",
            str(out),
            "--template-dir",
            str(TEMPLATES),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "missing scaffold-specification.json" in r.stderr


def test_atomic_rollback_on_write_error(tmp_path, monkeypatch):
    # A mid-loop OSError rolls back run_scaffold's own files; re-raises. (in-process; U1)
    spec_path = _write_spec(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    calls = {"n": 0}
    real_write = scaffold._render.write_text

    def boom(path, content):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk full")
        return real_write(path, content)

    monkeypatch.setattr(scaffold._render, "write_text", boom)
    with pytest.raises(OSError):
        scaffold.render(spec_path, out, TEMPLATES)
    # the first two written files were rolled back (none of run_scaffold's own output remains)
    assert not (out / "tb/uvm/interface/m_drv_if.sv").exists()
