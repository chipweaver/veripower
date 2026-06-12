"""Tests for derive_scaffold.py canonical agent-shape consumption (_agent_io)."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCAFFOLD = ROOT / "skills/simulation/scripts/derive_scaffold.py"

_spec = importlib.util.spec_from_file_location("derive_scaffold", SCAFFOLD)
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)


def test_agent_io_reads_canonical_nested_shape():
    """Canonical materialized agent → (signals, fields) read verbatim."""
    agent = {
        "name": "ctrl",
        "mode": "active",
        "interface": {
            "signals": [{"name": "wdata", "width": 32}, {"name": "wen", "width": 1}]
        },
        "transaction": {
            "fields": [{"name": "wdata", "width": 32, "type": "logic", "rand": True}]
        },
    }
    signals, fields = ds._agent_io(agent)
    assert signals == [{"name": "wdata", "width": 32}, {"name": "wen", "width": 1}]
    assert fields == [{"name": "wdata", "width": 32, "type": "logic", "rand": True}]


def test_agent_io_empty_signals_fails_loud():
    """An agent with no interface.signals is root cause A — fail loud, never emit
    a degenerate empty interface."""
    agent = {"name": "ctrl", "mode": "active", "interface": {"signals": []}}
    with pytest.raises(SystemExit) as ei:
        ds._agent_io(agent)
    assert "ctrl" in str(ei.value)
    assert "interface.signals" in str(ei.value)


def test_agent_io_missing_interface_fails_loud():
    """A legacy/flat agent (no interface block) fails loud rather than silently
    producing an empty interface."""
    agent = {
        "name": "ctrl",
        "mode": "active",
        "driver_signals": ["wdata"],
        "monitor_signals": [],
    }
    with pytest.raises(SystemExit) as ei:
        ds._agent_io(agent)
    assert "ctrl" in str(ei.value) and "interface.signals" in str(ei.value)


def test_check_compare_txn_list_raises():
    with pytest.raises(SystemExit) as ei:
        ds._check_str_or_omitted(["a", "b"], "scoreboard.compare_txn", "m")
    assert "compare_txn" in str(ei.value)


def test_check_compare_txn_omitted_ok():
    ds._check_str_or_omitted("", "scoreboard.compare_txn", "m")  # no raise
    ds._check_str_or_omitted(None, "scoreboard.compare_txn", "m")  # no raise


def test_check_inports_string_raises():
    with pytest.raises(SystemExit) as ei:
        ds._check_list_or_omitted("m_drv_txn", "rm.inports")
    assert "inports" in str(ei.value)


def test_check_seqs_string_raises():
    with pytest.raises(SystemExit) as ei:
        ds._check_list_or_omitted("smoke", "tests[].seqs")
    assert "seqs" in str(ei.value)


def test_check_list_omitted_ok():
    ds._check_list_or_omitted([], "rm.inports")  # no raise
    ds._check_list_or_omitted(None, "rm.inports")  # no raise


def test_obs_name_strips_canonical_txn():
    """Oracle (hand-written expected, NOT the expression re-typed): the gate's _obs_name
    recovers the agent name from the canonical '<module>_<agent>_txn' form and from a bare
    name. Replaces the prior self-equality (tautological) test. The global-.replace edge case
    for an agent name that itself contains the module prefix / '_txn' is a known, accepted
    limitation — mirrored by the consumer and rejected loudly by the gate — so it is
    deliberately NOT asserted here."""
    import importlib.util

    vs_path = ROOT / "skills/simulation-plan/scripts/validate_scaffold.py"
    spec = importlib.util.spec_from_file_location("validate_scaffold", vs_path)
    vs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vs)
    assert vs._obs_name("m_obs_txn", "m") == "obs"
    assert vs._obs_name("obs", "m") == "obs"
    assert vs._obs_name("m_wb_slave_agent_txn", "m") == "wb_slave_agent"


# --- Render-level regression (U3): render a real scaffold-spec into tmp, license-free.
# No simulator: structural assertions on the rendered tree only. Full render->elaborate
# of the bare stub tree requires a UVM simulator and lives in a separate simulator-gated
# CI suite (see plan §U3), NOT here.
TEMPLATE_DIR = ROOT / "skills/simulation/templates/scaffold"

RENDER_SPEC = {
    "module": "m",
    "top": "m_dut",
    "primary_clock": {"dut_port_name": "clk", "period_ns": 10.0},
    "reset": {"dut_port_name": "rst_n"},
    "agents": [
        {
            "name": "drv",
            "mode": "active",
            "interface": {"signals": [{"name": "wdata", "width": 32}, {"name": "wen", "width": 1}]},
            "transaction": {"fields": [{"name": "wdata", "width": 32, "rand": True}]},
        },
        {
            "name": "obs",
            "mode": "passive",
            "interface": {"signals": [{"name": "rdata", "width": 32}]},
            "transaction": {"fields": [{"name": "rdata", "width": 32}]},
        },
    ],
    "rm": {"name": "rule_rm", "inports": ["m_drv_txn"]},
    "scoreboard": {"name": "scoreboard", "compare_txn": "m_obs_txn"},
    "sequences": [{"name": "smoke", "agent": "drv"}],
    "tests": [{"name": "t_smoke", "feature": "F0", "seqs": ["smoke"]}],
}


def _render(tmp_path, spec=RENDER_SPEC):
    """Run run_scaffold(spec) into tmp_path/out and return the out dir."""
    import json

    plan = tmp_path / "scaffold-specification.json"
    plan.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "out"
    ds.run_scaffold(plan, TEMPLATE_DIR, out)
    return out


def test_render_passive_agent_emits_driver_file(tmp_path):
    """U2: every agent (incl. passive) gets a driver class so agent_agent.sv's
    unconditional `m_driver` type declaration resolves; passive never instantiates it."""
    out = _render(tmp_path)
    assert (out / "tb/uvm/agent/m_drv_driver.sv").is_file()
    assert (out / "tb/uvm/agent/m_obs_driver.sv").is_file()  # passive agent's driver


def test_render_tb_pkg_includes_passive_driver(tmp_path):
    """U2: tb_pkg must `include` the passive agent's driver (the type agent_agent.sv:6
    declares), else the include set is missing the type and elaboration fails."""
    out = _render(tmp_path)
    pkg = (out / "tb/uvm/pkg/tb_pkg.sv").read_text(encoding="utf-8")
    assert '`include "m_obs_driver.sv"' in pkg
    # driver-before-agent ordering within each agent's include group
    assert pkg.index('`include "m_obs_driver.sv"') < pkg.index('`include "m_obs_agent.sv"')


def test_render_produces_full_tree(tmp_path):
    """U3: a valid spec renders the expected core files without crashing."""
    out = _render(tmp_path)
    for rel in [
        "tb/uvm/env/m_env.sv",
        "tb/uvm/top/m_dut_tb_top.sv",
        "tb/uvm/pkg/tb_pkg.sv",
        "filelist.f",
        "tests/testlist.json",
    ]:
        assert (out / rel).is_file(), f"missing {rel}"


def test_render_tb_pkg_env_before_base_test(tmp_path):
    """U2②: base_test.sv declares `MY_MODULE_env m_env;` and creates it, so its include
    MUST come AFTER the env include in tb_pkg, else SV hits 'should be a valid type'."""
    out = _render(tmp_path)
    pkg = (out / "tb/uvm/pkg/tb_pkg.sv").read_text(encoding="utf-8")
    assert pkg.index('`include "m_env.sv"') < pkg.index('`include "base_test.sv"')
