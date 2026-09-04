"""Tests for the simplan materialize-scaffold verb.

It copies nothing into the scaffold — simulation reads top-io.json / clocks.json itself and the
check hints by id. What is left is validating the agent-to-group assignment."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-plan/scripts/simplan/__main__.py"


def _p(name, direction, role, group, width=1):
    r = {
        "name": name,
        "direction": direction,
        "width": width,
        "clock_domain": "clk",
        "interface_group": group,
        "role": role,
    }
    if role == "reset":
        r["reset_polarity"] = 0
        r["reset_kind"] = "async"
    return r


TOP_IO = [
    _p("clk", "input", "clock", "cfg"),
    _p("rst_n", "input", "reset", "cfg"),
    _p("wdata", "input", "data", "cfg", 32),
    _p("wen", "input", "data", "cfg"),
    _p("rdata", "output", "data", "stat", 32),
]


def _write(tmp_path, scaffold, top_io=None):
    """tmp_path doubles as the spec workdir."""
    sc = tmp_path / "tb-scaffold.json"
    sc.write_text(json.dumps(scaffold))
    (tmp_path / "top-io.json").write_text(
        json.dumps(TOP_IO if top_io is None else top_io)
    )
    return tmp_path, sc


def _run(spec, sc, check=True):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "materialize-scaffold",
            "--plan",
            str(sc.parent),
            "--spec",
            str(spec),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def _scaffold(agents):
    return {"module": "m", "top": "t", "agents": agents, "testpoints": []}


def test_missing_top_io_fails_loud(tmp_path):
    spec, sc = _write(
        tmp_path,
        _scaffold([{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]),
    )
    (tmp_path / "top-io.json").unlink()
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0 and "top-io.json" in proc.stderr


def test_unknown_group_fails_loud(tmp_path):
    spec, sc = _write(
        tmp_path,
        _scaffold([{"name": "x", "mode": "active", "interface_groups": ["nope"]}]),
    )
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "nope" in proc.stderr and "cfg" in proc.stderr


def test_missing_interface_groups_fails_loud(tmp_path):
    spec, sc = _write(tmp_path, _scaffold([{"name": "x", "mode": "active"}]))
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "interface_groups" in proc.stderr


def test_the_scaffold_is_left_untouched(tmp_path):
    spec, sc = _write(
        tmp_path,
        _scaffold([{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]),
    )
    before = sc.read_text()
    _run(spec, sc)
    assert sc.read_text() == before


def test_duplicate_signal_name_within_agent_fails_loud(tmp_path):
    io = json.loads(json.dumps(TOP_IO))
    io.append(
        _p("wdata", "input", "data", "cfg", 8)
    )  # duplicate of the cfg-group wdata
    spec, sc = _write(
        tmp_path,
        _scaffold([{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]),
        top_io=io,
    )
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "duplicate signal name" in proc.stderr and "wdata" in proc.stderr


def test_malformed_json_fails_loud(tmp_path):
    spec, sc = _write(tmp_path, _scaffold([]))
    (spec / "top-io.json").write_text("{ not: valid json ]")
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "not valid JSON" in proc.stderr and "Traceback" not in proc.stderr


def test_duplicate_group_fails_loud(tmp_path):
    spec, sc = _write(
        tmp_path,
        _scaffold(
            [{"name": "a", "mode": "active", "interface_groups": ["cfg", "cfg"]}]
        ),
    )
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "duplicate" in proc.stderr


def test_agent_whose_groups_hold_only_clk_rst_fails_loud(tmp_path):
    """The bench drives clock and reset, so such an agent has nothing to drive or observe."""
    top_io = [
        _p("clk", "input", "clock", "bench"),
        _p("rst_n", "input", "reset", "bench"),
        _p("wdata", "input", "data", "cfg", 32),
    ]
    spec, sc = _write(
        tmp_path,
        _scaffold([{"name": "a", "mode": "active", "interface_groups": ["bench"]}]),
        top_io=top_io,
    )
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0 and "no data ports" in proc.stderr


def test_the_dut_is_not_copied_into_the_scaffold(tmp_path):
    """A stored copy could disagree with top-io.json after either moved, and had no totality:
    a port absent from it rendered as a DUT port bound to nothing."""
    spec, sc = _write(
        tmp_path,
        _scaffold([{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]),
    )
    _run(spec, sc)
    out = json.loads(sc.read_text())
    assert "primary_clock" not in out and "reset" not in out
    assert "interface" not in out["agents"][0]
    assert "transaction" not in out["agents"][0]
