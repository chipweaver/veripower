"""Tests for the simplan materialize-scaffold verb — fills scaffold agents[] signals + transaction.fields
(clk/rst excluded), primary_clock, reset, and inlined_check_hints[] from plan-data.json."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-plan/scripts/simplan/__main__.py"

PLAN = {
    "interfaces": [
        {
            "signal_name": "clk",
            "direction": "input",
            "width": "1",
            "interface_group": "cfg",
            "role": "clock",
        },
        {
            "signal_name": "rst_n",
            "direction": "input",
            "width": "1",
            "interface_group": "cfg",
            "role": "reset",
        },
        {
            "signal_name": "wdata",
            "direction": "input",
            "width": "32",
            "interface_group": "cfg",
            "role": "data",
        },
        {
            "signal_name": "wen",
            "direction": "input",
            "width": "1",
            "interface_group": "cfg",
            "role": "data",
        },
        {
            "signal_name": "rdata",
            "direction": "output",
            "width": "32",
            "interface_group": "stat",
            "role": "data",
        },
    ],
    "clocks": [{"clock_name": "clk", "period_ns": "10.0", "relationship": "primary"}],
    "check_hints": [],
}


def _write(tmp_path, plan_data, scaffold):
    pd = tmp_path / "plan-data.json"
    sc = tmp_path / "scaffold-specification.json"
    pd.write_text(json.dumps(plan_data))
    sc.write_text(json.dumps(scaffold))
    return pd, sc


def _run(pd, sc, check=True):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "materialize-scaffold",
            "--plan-data",
            str(pd),
            "--scaffold",
            str(sc),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def _scaffold(agents):
    return {"module": "m", "top": "t", "agents": agents, "testpoints": []}


def test_interface_keeps_clkrst_transaction_excludes_them(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, PLAN, sc_in)
    _run(pd, sc)
    agent = json.loads(sc.read_text())["agents"][0]
    assert [s["name"] for s in agent["interface"]["signals"]] == [
        "clk",
        "rst_n",
        "wdata",
        "wen",
    ]
    assert [f["name"] for f in agent["transaction"]["fields"]] == ["wdata", "wen"]


def test_primary_clock_and_reset_derived(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, PLAN, sc_in)
    _run(pd, sc)
    out = json.loads(sc.read_text())
    assert out["primary_clock"] == {"dut_port_name": "clk", "period_ns": "10.0"}
    assert out["reset"] == {"dut_port_name": "rst_n"}


def test_no_primary_relationship_fails_loud(tmp_path):
    plan = json.loads(json.dumps(PLAN))
    plan["clocks"][0]["relationship"] = "async"
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, plan, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "primary" in proc.stderr.lower()


def test_no_reset_role_fails_loud(tmp_path):
    plan = json.loads(json.dumps(PLAN))
    plan["interfaces"][1]["role"] = "data"  # rst_n no longer role=reset
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, plan, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "reset" in proc.stderr.lower()


def test_empty_role_fails_loud(tmp_path):
    plan = json.loads(json.dumps(PLAN))
    plan["interfaces"][2]["role"] = ""  # wdata missing gated Role
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, plan, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "role" in proc.stderr.lower()


def test_unknown_group_fails_loud(tmp_path):
    sc_in = _scaffold([{"name": "x", "mode": "active", "interface_groups": ["nope"]}])
    pd, sc = _write(tmp_path, PLAN, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "nope" in proc.stderr and "cfg" in proc.stderr


def test_missing_interface_groups_fails_loud(tmp_path):
    sc_in = _scaffold([{"name": "x", "mode": "active"}])
    pd, sc = _write(tmp_path, PLAN, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "interface_groups" in proc.stderr


def test_non_numeric_width_fails_loud(tmp_path):
    plan = json.loads(json.dumps(PLAN))
    plan["interfaces"][2]["width"] = "[7:0]"
    sc_in = _scaffold([{"name": "a", "mode": "active", "interface_groups": ["cfg"]}])
    pd, sc = _write(tmp_path, plan, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "width" in proc.stderr


def test_idempotent(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, PLAN, sc_in)
    _run(pd, sc)
    first = sc.read_text()
    _run(pd, sc)
    assert sc.read_text() == first


def test_empty_direction_data_port_fails_loud(tmp_path):
    # A4: a data-role port with empty Direction can't be classed driver vs monitor →
    # the generated TB is wrong. Direction is gated for data roles; fail loud.
    plan = json.loads(json.dumps(PLAN))
    plan["interfaces"][2]["direction"] = ""  # wdata (role=data) has no Direction
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, plan, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "Direction" in proc.stderr and "wdata" in proc.stderr


def test_duplicate_signal_name_within_agent_fails_loud(tmp_path):
    # A7: the same signal name appearing twice within one agent's groups would emit
    # duplicate SV declarations. Must fail loud.
    plan = json.loads(json.dumps(PLAN))
    plan["interfaces"].append(
        {
            "signal_name": "wdata",  # duplicate of the existing cfg-group wdata
            "direction": "input",
            "width": "8",
            "interface_group": "cfg",
            "role": "data",
        }
    )
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    pd, sc = _write(tmp_path, plan, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "duplicate signal" in proc.stderr and "wdata" in proc.stderr


def test_malformed_json_fails_loud(tmp_path):
    # A6: a JSON syntax error in plan-data.json (or scaffold) must fail loud with a
    # fix-oriented message, not a raw traceback.
    pd = tmp_path / "plan-data.json"
    sc = tmp_path / "scaffold-specification.json"
    pd.write_text("{ not: valid json ]")
    sc.write_text(json.dumps(_scaffold([])))
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "not valid JSON" in proc.stderr and "Traceback" not in proc.stderr


def test_duplicate_group_fails_loud(tmp_path):
    sc_in = _scaffold(
        [{"name": "a", "mode": "active", "interface_groups": ["cfg", "cfg"]}]
    )
    pd, sc = _write(tmp_path, PLAN, sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "duplicate" in proc.stderr


def test_multiple_groups_union_excludes_clkrst(tmp_path):
    sc_in = _scaffold(
        [{"name": "all", "mode": "passive", "interface_groups": ["cfg", "stat"]}]
    )
    pd, sc = _write(tmp_path, PLAN, sc_in)
    _run(pd, sc)
    agent = json.loads(sc.read_text())["agents"][0]
    # interface.signals = union of both groups, clk/rst KEPT
    assert [s["name"] for s in agent["interface"]["signals"]] == [
        "clk",
        "rst_n",
        "wdata",
        "wen",
        "rdata",
    ]
    # transaction.fields = union minus clk/rst
    assert [f["name"] for f in agent["transaction"]["fields"]] == [
        "wdata",
        "wen",
        "rdata",
    ]


CHECK_HINTS = [
    {
        "check_id": "CHK-00",
        "implementation_detail": "write reg",
        "implementation_detail_verbatim": "reg[addr] <= wdata",
        "observable": "rdata",
        "reference_rule": "reg[addr]=wdata",
        "latency": "1",
        "reset_behavior": "0",
    },
    {
        "check_id": "CHK-01",
        "implementation_detail": "narrative only",
        "implementation_detail_verbatim": "",
        "observable": "",
        "reference_rule": "",
        "latency": "",
        "reset_behavior": "",
    },
]


def _plan_with_hints():
    plan = json.loads(json.dumps(PLAN))
    plan["check_hints"] = CHECK_HINTS
    return plan


def test_inline_prefers_verbatim(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-0", "covers": ["CHK-00"]}]
    pd, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(pd, sc)
    tp = json.loads(sc.read_text())["testpoints"][0]
    inlined = tp["inlined_check_hints"][0]
    assert inlined["check_id"] == "CHK-00"
    assert (
        inlined["implementation_detail"] == "reg[addr] <= wdata"
    )  # verbatim, not summary
    assert inlined["observable"] == "rdata"


def test_inline_falls_back_to_summary_when_verbatim_empty(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-1", "covers": ["CHK-01"]}]
    pd, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(pd, sc)
    inlined = json.loads(sc.read_text())["testpoints"][0]["inlined_check_hints"][0]
    assert inlined["implementation_detail"] == "narrative only"
    assert set(inlined.keys()) == {
        "check_id",
        "implementation_detail",
    }  # all empty optionals dropped


def test_inline_empty_covers_yields_empty_inline(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-IRQ", "covers": []}]
    pd, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(pd, sc)
    assert json.loads(sc.read_text())["testpoints"][0]["inlined_check_hints"] == []


def test_inline_unknown_covers_fails_loud(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-X", "covers": ["CHK-99"]}]
    pd, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    proc = _run(pd, sc, check=False)
    assert proc.returncode != 0
    assert "CHK-99" in proc.stderr


def test_inline_idempotent_over_nonempty_covers(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-0", "covers": ["CHK-00"]}]
    pd, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(pd, sc)
    first = sc.read_text()
    _run(pd, sc)
    assert sc.read_text() == first  # re-materializing the inline is stable
