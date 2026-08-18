"""Tests for the simplan materialize-scaffold verb.

It no longer copies the DUT into the scaffold — simulation reads top-io.json / clocks.json
itself. What is left is validating the agent-to-group assignment and inlining the check hints
and feature names the human gate is held over."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-plan/scripts/simplan/__main__.py"

HINTS: list = []


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


CLOCKS = [{"name": "clk", "period_ns": 10.0, "relationship": "primary"}]


FEATURES = [
    {
        "id": "F-01",
        "name": "Register write path",
        "description": "d",
        "mode_interface": "m",
        "priority": "must",
        "happy_path": "h",
        "corner_cases": "c",
        "negative_cases": "n",
    }
]


def _write(tmp_path, hints, scaffold, clocks=None, top_io=None, features=None):
    """tmp_path doubles as the spec workdir: manifest + sidecars + check-hints/."""
    sc = tmp_path / "tb-scaffold.json"
    sc.write_text(json.dumps(scaffold))
    (tmp_path / "features.json").write_text(
        json.dumps(FEATURES if features is None else features)
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "c", "doc": "c.md"}]})
    )
    (tmp_path / "clocks.json").write_text(
        json.dumps(CLOCKS if clocks is None else clocks)
    )
    (tmp_path / "top-io.json").write_text(
        json.dumps(TOP_IO if top_io is None else top_io)
    )
    hd = tmp_path / "check-hints"
    hd.mkdir(exist_ok=True)
    (hd / "c.json").write_text(json.dumps(hints))
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


def _scaffold(agents):
    return {"module": "m", "top": "t", "agents": agents, "testpoints": []}


def test_missing_clocks_json_fails_loud(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    (tmp_path / "clocks.json").unlink()
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0 and "clocks.json" in proc.stderr


def test_unknown_group_fails_loud(tmp_path):
    sc_in = _scaffold([{"name": "x", "mode": "active", "interface_groups": ["nope"]}])
    spec, sc = _write(tmp_path, HINTS, sc_in)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "nope" in proc.stderr and "cfg" in proc.stderr


def test_missing_interface_groups_fails_loud(tmp_path):
    sc_in = _scaffold([{"name": "x", "mode": "active"}])
    spec, sc = _write(tmp_path, HINTS, sc_in)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "interface_groups" in proc.stderr


def test_idempotent(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    _run(spec, sc)
    first = sc.read_text()
    _run(spec, sc)
    assert sc.read_text() == first


def test_duplicate_signal_name_within_agent_fails_loud(tmp_path):
    # The same signal name appearing twice within one agent's groups would emit
    # duplicate SV declarations. Must fail loud.
    io = json.loads(json.dumps(TOP_IO))
    io.append(
        _p("wdata", "input", "data", "cfg", 8)
    )  # duplicate of the cfg-group wdata
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in, top_io=io)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "duplicate signal name" in proc.stderr and "wdata" in proc.stderr


def test_malformed_json_fails_loud(tmp_path):
    # A JSON syntax error in a sidecar (or the scaffold) must fail loud with a
    # fix-oriented message, not a raw traceback.
    spec, sc = _write(tmp_path, HINTS, _scaffold([]))
    (spec / "clocks.json").write_text("{ not: valid json ]")
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "not valid JSON" in proc.stderr and "Traceback" not in proc.stderr


def test_duplicate_group_fails_loud(tmp_path):
    sc_in = _scaffold(
        [{"name": "a", "mode": "active", "interface_groups": ["cfg", "cfg"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "duplicate" in proc.stderr


def _plan_with_hints():
    return CHECK_HINTS


def test_inline_prefers_verbatim(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-0", "intent": "i", "covers": ["CHK-00"]}]
    spec, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(spec, sc)
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
    sc_in["testpoints"] = [{"id": "TP-1", "intent": "i", "covers": ["CHK-01"]}]
    spec, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(spec, sc)
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
    sc_in["testpoints"] = [{"id": "TP-IRQ", "intent": "i", "covers": []}]
    spec, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(spec, sc)
    assert json.loads(sc.read_text())["testpoints"][0]["inlined_check_hints"] == []


def test_inline_unknown_covers_fails_loud(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-X", "intent": "i", "covers": ["CHK-99"]}]
    spec, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "CHK-99" in proc.stderr


def test_inline_idempotent_over_nonempty_covers(tmp_path):
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    sc_in["testpoints"] = [{"id": "TP-0", "intent": "i", "covers": ["CHK-00"]}]
    spec, sc = _write(tmp_path, _plan_with_hints(), sc_in)
    _run(spec, sc)
    first = sc.read_text()
    _run(spec, sc)
    assert sc.read_text() == first  # re-materializing the inline is stable


def _scaffold_with_tests(tests):
    sc = _scaffold([{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}])
    sc["tests"] = tests
    return sc


def test_feature_name_injected_from_features_json(tmp_path):
    # The Feature column of case-results-summary.md is generated from this; before the
    # injection existed the scaffold fabricated feature_name = feature, so that column was
    # identically the FeatureID column.
    sc_in = _scaffold_with_tests(
        [{"name": "t1", "feature": "F-01", "test_id": "T-01", "suites": ["smoke"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    _run(spec, sc)
    got = json.loads(sc.read_text())["tests"][0]
    assert got["feature_name"] == "Register write path"
    assert got["feature_name"] != got["feature"]


def test_feature_name_unknown_id_fails_loud(tmp_path):
    sc_in = _scaffold_with_tests(
        [{"name": "t1", "feature": "F-99", "test_id": "T-01", "suites": ["regress"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "F-99" in proc.stderr


def test_feature_name_absent_feature_fails_loud(tmp_path):
    sc_in = _scaffold_with_tests(
        [{"name": "t1", "test_id": "T-01", "suites": ["regress"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0
    assert "feature" in proc.stderr


def test_feature_name_reinjection_is_stable(tmp_path):
    sc_in = _scaffold_with_tests(
        [{"name": "t1", "feature": "F-01", "test_id": "T-01", "suites": ["smoke"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    _run(spec, sc)
    first = sc.read_text()
    _run(spec, sc)
    assert sc.read_text() == first


def test_agent_whose_groups_hold_only_clk_rst_fails_loud(tmp_path):
    """The bench drives clock and reset, so such an agent has nothing to drive or observe."""
    top_io = [
        _p("clk", "input", "clock", "bench"),
        _p("rst_n", "input", "reset", "bench"),
        _p("wdata", "input", "data", "cfg", 32),
    ]
    sc_in = _scaffold([{"name": "a", "mode": "active", "interface_groups": ["bench"]}])
    spec, sc = _write(tmp_path, HINTS, sc_in, top_io=top_io)
    proc = _run(spec, sc, check=False)
    assert proc.returncode != 0 and "no data ports" in proc.stderr


def test_the_dut_is_not_copied_into_the_scaffold(tmp_path):
    """A stored copy could disagree with top-io.json after either moved, and had no totality:
    a port absent from it rendered as a DUT port bound to nothing."""
    sc_in = _scaffold(
        [{"name": "cfg_a", "mode": "active", "interface_groups": ["cfg"]}]
    )
    spec, sc = _write(tmp_path, HINTS, sc_in)
    _run(spec, sc)
    out = json.loads(sc.read_text())
    assert "primary_clock" not in out and "reset" not in out
    assert "interface" not in out["agents"][0]
    assert "transaction" not in out["agents"][0]
