"""sim's agent-to-boundary assignment guard.

The scaffold no longer carries a copy of the DUT's signals, so what is left to check is the
assignment the plan author made: the agents' interface_groups must partition top-io.json's
data ports. The port walk is what makes a missing binding inexpressible — before it, an
unclaimed port rendered as an open DUT port, which Verilog accepts silently.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim._boundary import Boundary  # noqa: E402
from sim._guards import dut_port_map  # noqa: E402

TOP_IO = [
    {
        "name": "clk",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "bench",
        "role": "clock",
    },
    {
        "name": "rst_n",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "bench",
        "role": "reset",
        "reset_polarity": 0,
        "reset_kind": "async",
    },
    {
        "name": "req",
        "direction": "input",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "a",
        "role": "data",
    },
    {
        "name": "ack",
        "direction": "output",
        "width": 1,
        "clock_domain": "clk",
        "interface_group": "b",
        "role": "data",
    },
]
CLOCKS = [{"name": "clk", "period_ns": 10.0, "relationship": "primary"}]


def _boundary(tmp_path, top_io=None, clocks=None):
    (tmp_path / "top-io.json").write_text(json.dumps(top_io or TOP_IO))
    (tmp_path / "clocks.json").write_text(json.dumps(clocks or CLOCKS))
    return Boundary(tmp_path)


AGENTS = [
    {"name": "d", "mode": "active", "interface_groups": ["a"]},
    {"name": "o", "mode": "passive", "interface_groups": ["b"]},
]


def test_port_map_binds_every_data_port_and_no_bench_port(tmp_path):
    out = dut_port_map(AGENTS, _boundary(tmp_path))
    assert out.startswith(",\n")
    assert ".req(d_if.req)" in out and ".ack(o_if.ack)" in out
    # the bench drives these itself; tb_top emits them, not the port map
    assert "clk" not in out and "rst_n" not in out


def test_port_map_follows_top_io_order(tmp_path):
    """The walk is over the boundary, which is what makes an omission impossible."""
    out = dut_port_map(AGENTS, _boundary(tmp_path))
    assert out.index(".req(") < out.index(".ack(")


def test_unclaimed_data_port_exits(tmp_path):
    top_io = TOP_IO + [
        {
            "name": "orphan",
            "direction": "input",
            "width": 4,
            "clock_domain": "clk",
            "interface_group": "nobody",
            "role": "data",
        }
    ]
    with pytest.raises(SystemExit) as e:
        dut_port_map(AGENTS, _boundary(tmp_path, top_io))
    assert "orphan" in str(e.value) and "no agent claims" in str(e.value)


def test_group_claimed_twice_exits(tmp_path):
    agents = [
        {"name": "d", "mode": "active", "interface_groups": ["a", "b"]},
        {"name": "o", "mode": "passive", "interface_groups": ["b"]},
    ]
    with pytest.raises(SystemExit) as e:
        dut_port_map(agents, _boundary(tmp_path))
    assert "claimed by both" in str(e.value)


def test_agent_with_only_bench_ports_exits(tmp_path):
    agents = [
        {"name": "d", "mode": "active", "interface_groups": ["bench"]},
        {"name": "o", "mode": "passive", "interface_groups": ["b"]},
    ]
    with pytest.raises(SystemExit) as e:
        dut_port_map(agents, _boundary(tmp_path))
    assert "no data ports" in str(e.value)
