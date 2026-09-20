# tests/unit/test_parse_coverage.py
"""Tests for skills/simulation/templates/infra/scripts/parse_coverage.py (urg text report -> dict)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(
    0, str(ROOT / "skills" / "simulation" / "templates" / "infra" / "scripts")
)
FIX = Path(__file__).resolve().parent / "fixtures" / "parse_coverage"
FIX5 = Path(__file__).resolve().parent / "fixtures" / "parse_coverage-5col"

import parse_coverage as pc  # noqa: E402


def test_instance_subtrees_include_children_and_keep_peer_instances_separate():
    rows = {
        r["name"]: r for r in pc.parse_instances((FIX / "instances.txt").read_text())
    }
    dut = "tb.dut"
    assert rows[dut]["cond"] == 80
    assert rows[dut]["toggle"] == 70
    assert rows[dut]["fsm"] is None
    assert rows[dut + ".channel_a"]["toggle"] == 75
    assert rows[dut + ".channel_b"]["toggle"] == 50


def test_instance_subtrees_follow_report_columns():
    text = "Module Instance : tb.dut\nInstance's subtree :\n\nSCORE LINE TOGGLE\n91 92 90\n"
    assert pc.parse_instances(text) == [
        dict(name="tb.dut", score=91, line=92, toggle=90)
    ]


@pytest.mark.parametrize("body", ["", "SCORE LINE\n\nModule :\nSCORE LINE\n100 100\n"])
def test_missing_subtree_cannot_borrow_a_module_table(body):
    with pytest.raises(ValueError, match="subtree"):
        pc.parse_instances("Module Instance : tb.dut\nInstance's subtree :\n" + body)


def test_duplicate_instance_path_is_not_arbitrarily_selected():
    text = "Module Instance : tb.dut\nInstance's subtree :\nSCORE LINE\n90 91\n"
    with pytest.raises(ValueError, match="duplicate"):
        pc.parse_instances(text + text)


def test_parse_aggregate_dims():
    agg = pc.parse_aggregate((FIX / "dashboard.txt").read_text())
    assert agg == pytest.approx(
        {
            "score": 47.80,
            "line": 70.81,
            "cond": 40.26,
            "toggle": 34.52,
            "fsm": 31.25,
            "branch": 62.16,
        },
        rel=1e-3,
    )


def test_columns_come_from_the_header_not_from_an_assumed_set():
    # A five-column table must not borrow the next table's instance-name column.
    agg = pc.parse_aggregate((FIX5 / "dashboard.txt").read_text())
    assert agg == pytest.approx(
        {"score": 48.00, "line": 82.42, "cond": 41.17, "toggle": 50.25, "fsm": 18.18},
        rel=1e-3,
    )
    assert "branch" not in agg  # a dim urg did not measure is absent, never guessed


def test_parse_aggregate_missing_returns_none():
    assert pc.parse_aggregate("no coverage summary here") is None


def test_build_writes_structural_coverage_json(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text((FIX / "dashboard.txt").read_text())
    with (cov_dir / "modinfo.txt").open("a") as f:
        f.write("\n" + (FIX / "instances.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    rc = pc.build(cov_dir, out)
    assert rc == 0 and out.is_file()
    import json

    data = json.loads(out.read_text())
    assert data["aggregate"]["fsm"] == pytest.approx(31.25)
    assert any(m["name"] == "tb.dut" for m in data["per_instance"])
    assert "L-2016.06" in data.get("urg_version", "")


def test_parse_uncovered_names_branch_cond_and_fsm_items():
    items = pc.parse_uncovered((FIX / "modinfo.txt").read_text())
    assert items == [
        {
            "module": "controller",
            "kind": "branch",
            "line": 11,
            "detail": "if (ready) transfer <= 1'b1;",
        },
        {
            "module": "controller",
            "kind": "cond",
            "line": 20,
            "detail": "(enable && ready)",
        },
        {"module": "controller", "kind": "cond", "line": 21, "detail": "ready"},
        {"module": "controller", "kind": "fsm", "line": 31, "detail": "BUSY->IDLE"},
    ]


def test_parse_uncovered_tolerates_unknown_format():
    assert pc.parse_uncovered("Module : foo\nnothing recognisable here\n") == []


def test_build_without_modinfo_refuses_to_emit(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text((FIX / "dashboard.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    with pytest.raises(SystemExit, match="no instance coverage"):
        pc.build(cov_dir, out)
    assert not out.exists()


def test_build_includes_uncovered_when_modinfo_present(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text((FIX / "dashboard.txt").read_text())
    (cov_dir / "modinfo.txt").write_text((FIX / "modinfo.txt").read_text())
    with (cov_dir / "modinfo.txt").open("a") as f:
        f.write("\n" + (FIX / "instances.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    assert pc.build(cov_dir, out) == 0
    import json

    data = json.loads(out.read_text())
    assert len(data["uncovered"]) == 4
    assert data["aggregate"]["fsm"] == pytest.approx(31.25)  # unchanged by the addition


def test_build_fail_loud_when_dashboard_missing(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()  # no dashboard.txt
    with (cov_dir / "modinfo.txt").open("a") as f:
        f.write("\n" + (FIX / "instances.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    out.write_text('{"per_instance": [{"name": "stale", "line": 100}]}')
    with pytest.raises(SystemExit):
        pc.build(cov_dir, out)
    assert not out.exists()  # never emit a "claim met" file


def test_build_fail_loud_when_aggregate_unparseable(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text("garbage with no summary block")
    with (cov_dir / "modinfo.txt").open("a") as f:
        f.write("\n" + (FIX / "instances.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    with pytest.raises(SystemExit):
        pc.build(cov_dir, out)
    assert not out.exists()  # never emit a "claim met" file on unparseable input


@pytest.mark.parametrize("metric", ["TOGGLE", "FSM", "COND"])
def test_report_without_line_coverage_is_judged_by_requested_metric(tmp_path, metric):
    import json

    sys.path.insert(0, str(ROOT / "skills/simulation/scripts"))
    from sim.checks import coverage_gate

    table = f"SCORE {metric}\n84.5 84.5\n"
    (tmp_path / "dashboard.txt").write_text("Total Coverage Summary\n" + table)
    (tmp_path / "modinfo.txt").write_text(
        "Module Instance : bench.dut\nInstance's subtree :\n" + table
    )
    destination = tmp_path / "coverage.json"
    assert pc.build(tmp_path, destination) == 0
    coverage = json.loads(destination.read_text())
    assert "line" not in coverage["per_instance"][0]
    rows = [
        {
            "id": "present",
            "target": {"dim": "coverage_" + metric.lower(), "op": ">", "value": 80},
        },
        {"id": "absent", "target": {"dim": "coverage_line", "op": ">=", "value": 0}},
    ]
    errors, judged = coverage_gate(coverage, rows, "bench.dut")
    assert errors
    assert [(r["id"], r["met"], r["actual"]) for r in judged] == [
        ("present", True, 84.5),
        ("absent", False, None),
    ]
