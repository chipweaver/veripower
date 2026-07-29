# tests/unit/test_sim_guards.py
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import _guards  # noqa: E402


def test_agent_io_returns_signals_fields():
    ag = {
        "name": "drv",
        "interface": {"signals": [{"name": "a", "width": 1}]},
        "transaction": {"fields": [{"name": "d", "width": 8}]},
    }
    signals, fields = _guards._agent_io(ag)
    assert signals == [{"name": "a", "width": 1}]
    assert fields == [{"name": "d", "width": 8}]


def test_agent_io_empty_signals_exits():
    with pytest.raises(SystemExit):
        _guards._agent_io({"name": "drv", "interface": {"signals": []}})


def test_check_str_rejects_nonstr():
    with pytest.raises(SystemExit):
        _guards._check_str_or_omitted(["a"], "scoreboard.observer")
    _guards._check_str_or_omitted(None, "scoreboard.observer")  # omitted ok
    _guards._check_str_or_omitted("obs", "scoreboard.observer")  # str ok


def test_check_list_rejects_nonlist():
    with pytest.raises(SystemExit):
        _guards._check_list_or_omitted("ctrl", "rm.inports")
    _guards._check_list_or_omitted(None, "rm.inports")  # omitted ok
    _guards._check_list_or_omitted(["ctrl"], "rm.inports")  # list ok


def test_validate_ports_clk_collision():
    agents = [{"name": "drv", "interface": {"signals": [{"name": "clk", "width": 1}]}}]
    with pytest.raises(SystemExit):
        _guards.validate_ports(agents, "clk", "rst_n")


def test_validate_ports_dup_signal():
    agents = [
        {"name": "a", "interface": {"signals": [{"name": "x", "width": 1}]}},
        {"name": "b", "interface": {"signals": [{"name": "x", "width": 1}]}},
    ]
    with pytest.raises(SystemExit):
        _guards.validate_ports(agents, "clk", "rst_n")


def test_validate_ports_returns_port_map():
    agents = [{"name": "a", "interface": {"signals": [{"name": "x", "width": 1}]}}]
    out = _guards.validate_ports(agents, "clk", "rst_n")
    assert out.startswith(",\n")
    assert ".x(a_if.x)" in out
