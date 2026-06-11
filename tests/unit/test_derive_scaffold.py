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
