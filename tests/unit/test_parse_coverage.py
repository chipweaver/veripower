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
    # Verbatim urg L-2016.06 output from an OpenTitan DV run whose -metric left out
    # branch: five dim columns, not six. Assuming six walked past this row, latched onto
    # the next block's (Hierarchical coverage, which appends an instance NAME) and tried
    # to read that name as a number. The columns are printed above every table.
    agg = pc.parse_aggregate((FIX5 / "dashboard.txt").read_text())
    assert agg == pytest.approx(
        {"score": 48.00, "line": 82.42, "cond": 41.17, "toggle": 50.25, "fsm": 18.18},
        rel=1e-3,
    )
    assert "branch" not in agg  # a dim urg did not measure is absent, never guessed

    mods = {m["name"]: m for m in pc.parse_modules((FIX5 / "modlist.txt").read_text())}
    assert len(mods) == 34
    assert mods["uart_core"]["line"] == pytest.approx(81.03)
    assert "branch" not in mods["uart_core"]


def test_parse_aggregate_missing_returns_none():
    assert pc.parse_aggregate("no coverage summary here") is None


def test_parse_modules_with_na_dims():
    mods = {m["name"]: m for m in pc.parse_modules((FIX / "modlist.txt").read_text())}
    # sd_crc_16 has no COND/FSM -> '--' -> None (datapath-no-FSM skip case)
    assert mods["sd_crc_16"]["fsm"] is None
    assert mods["sd_crc_16"]["cond"] is None
    assert mods["sd_crc_16"]["line"] == pytest.approx(10.53)
    assert mods["sd_cmd_master"]["fsm"] == pytest.approx(75.00)


def test_build_writes_structural_coverage_json(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text((FIX / "dashboard.txt").read_text())
    (cov_dir / "modlist.txt").write_text((FIX / "modlist.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    rc = pc.build(cov_dir, out)
    assert rc == 0 and out.is_file()
    import json

    data = json.loads(out.read_text())
    assert data["aggregate"]["fsm"] == pytest.approx(31.25)
    assert any(m["name"] == "sd_crc_16" for m in data["per_module"])
    assert "L-2016.06" in data.get("urg_version", "")


def test_parse_uncovered_names_branch_cond_and_fsm_items():
    items = pc.parse_uncovered((FIX / "modinfo.txt").read_text())
    # every "Not Covered" row in the fixture becomes exactly one named item
    assert len(items) == 11
    assert {i["kind"] for i in items} == {"branch", "cond", "fsm"}
    assert {i["module"] for i in items} == {"mgpt_rmsnorm"}
    # the branch a percentage cannot name: the QMAX clamp's taken side, with its source line
    qmax = [i for i in items if i["line"] == 160 and i["kind"] == "branch"]
    assert len(qmax) == 1
    assert "QMAX" in qmax[0]["detail"]
    # SUB-EXPRESSION blocks carry their own LINE and must not be dropped
    assert any(i["kind"] == "cond" and i["line"] == 150 for i in items)
    # FSM rows carry the transition name, not source text
    assert any(i["kind"] == "fsm" and "->" in i["detail"] for i in items)


def test_parse_uncovered_tolerates_unknown_format():
    assert pc.parse_uncovered("Module : foo\nnothing recognisable here\n") == []


def test_build_without_modinfo_yields_empty_uncovered(tmp_path):
    """modinfo.txt is optional -- its absence must not fail the run or the gate."""
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text((FIX / "dashboard.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    assert pc.build(cov_dir, out) == 0
    import json

    assert json.loads(out.read_text())["uncovered"] == []


def test_build_includes_uncovered_when_modinfo_present(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text((FIX / "dashboard.txt").read_text())
    (cov_dir / "modlist.txt").write_text((FIX / "modlist.txt").read_text())
    (cov_dir / "modinfo.txt").write_text((FIX / "modinfo.txt").read_text())
    out = tmp_path / "structural-coverage.json"
    assert pc.build(cov_dir, out) == 0
    import json

    data = json.loads(out.read_text())
    assert len(data["uncovered"]) == 11
    assert data["aggregate"]["fsm"] == pytest.approx(31.25)  # unchanged by the addition


def test_build_fail_loud_when_dashboard_missing(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()  # no dashboard.txt
    out = tmp_path / "structural-coverage.json"
    with pytest.raises(SystemExit):
        pc.build(cov_dir, out)
    assert not out.exists()  # never emit a "claim met" file


def test_build_fail_loud_when_aggregate_unparseable(tmp_path):
    cov_dir = tmp_path / "cov_merge"
    cov_dir.mkdir()
    (cov_dir / "dashboard.txt").write_text("garbage with no summary block")
    out = tmp_path / "structural-coverage.json"
    with pytest.raises(SystemExit):
        pc.build(cov_dir, out)
    assert not out.exists()  # never emit a "claim met" file on unparseable input
