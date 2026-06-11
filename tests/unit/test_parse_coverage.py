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
