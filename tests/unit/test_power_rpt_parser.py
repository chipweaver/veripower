"""Tests for skills/power-analysis/scripts/power_rpt_parser.py"""

import json as _json
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "power-analysis" / "scripts"))

import power_rpt_parser as p  # noqa: E402
from power_rpt_parser import parse_total_power_mw  # noqa: E402

SAMPLE_RPT_MW = """\
****************************************
Report : power-analysis
****************************************
Hierarchy                Switch   Internal   Leakage      Total
                          Power      Power     Power      Power
-------------------------------------------------------------
top                     0.5000     0.6000    0.0200     1.1200 mW  (100.00%)
  u_core                0.3000     0.4000    0.0100     0.7100 mW   (63.39%)
  u_ram                 0.2000     0.2000    0.0100     0.4100 mW   (36.61%)
-------------------------------------------------------------
Total Power = 1.1200 mW
"""

SAMPLE_RPT_UW = """\
Total Power = 850.5 uW
"""

SAMPLE_RPT_W = """\
Total Power = 2.5 W
"""

SAMPLE_RPT_MISSING = """\
****************************************
Report : power-analysis
****************************************
No power-analysis data available.
"""


def test_parse_mw(tmp_path):
    f = tmp_path / "power_hier.rpt"
    f.write_text(SAMPLE_RPT_MW)
    assert parse_total_power_mw(f) == pytest.approx(1.12)


def test_parse_uw_converts_to_mw(tmp_path):
    f = tmp_path / "power_hier.rpt"
    f.write_text(SAMPLE_RPT_UW)
    assert parse_total_power_mw(f) == pytest.approx(0.8505)


def test_parse_w_converts_to_mw(tmp_path):
    f = tmp_path / "power_hier.rpt"
    f.write_text(SAMPLE_RPT_W)
    assert parse_total_power_mw(f) == pytest.approx(2500.0)


def test_parse_missing_returns_none(tmp_path):
    f = tmp_path / "power_hier.rpt"
    f.write_text(SAMPLE_RPT_MISSING)
    assert parse_total_power_mw(f) is None


def test_parse_nonexistent_file_returns_none(tmp_path):
    f = tmp_path / "nonexistent.rpt"
    assert parse_total_power_mw(f) is None


def _write_rpt(tmp_path, content):
    rpt = tmp_path / "power_hier.rpt"
    rpt.write_text(textwrap.dedent(content))
    return rpt


def test_parse_three_components(tmp_path):
    rpt = _write_rpt(
        tmp_path,
        """
        ...
        Cell Internal Power = 4.5000e-04 mW
        Net Switching Power = 6.2000e-04 mW
        Cell Leakage Power = 2.3000e-04 mW
        Total Power = 1.3000e-03 mW
        ...
    """,
    )
    parts = p.parse_three_components(rpt)
    assert parts == pytest.approx(
        {
            "internal_mw": 4.5e-4,
            "switching_mw": 6.2e-4,
            "leakage_mw": 2.3e-4,
        },
        rel=1e-3,
    )


def test_parse_three_components_missing(tmp_path):
    rpt = _write_rpt(tmp_path, "no power data here")
    assert p.parse_three_components(rpt) is None


def test_parse_annotation_coverage_averaged(tmp_path):
    """In SAIF-averaged mode, PT emits 'Annotated cell percentage = NNNN%'."""
    rpt = _write_rpt(
        tmp_path,
        """
        Annotated cell percentage  = 87.45%
    """,
    )
    cov = p.parse_annotation_coverage(rpt)
    assert cov == pytest.approx(0.8745, rel=1e-3)


def test_parse_annotation_coverage_missing(tmp_path):
    rpt = _write_rpt(tmp_path, "nothing here")
    assert p.parse_annotation_coverage(rpt) is None


def test_parse_toggle_region(tmp_path):
    rpt = _write_rpt(
        tmp_path,
        """
        ...
        SAIF time interval = 0 to 10000 ns
        ...
    """,
    )
    region = p.parse_toggle_region(rpt)
    assert region == "0ns-10000ns"


def _flat_rpt(total_mw, internal=None, switching=None, leakage=None):
    lines = []
    if internal is not None:
        lines += [
            f"Cell Internal Power = {internal:.4e} mW",
            f"Net Switching Power = {switching:.4e} mW",
            f"Cell Leakage Power = {leakage:.4e} mW",
        ]
    lines.append(f"Total Power = {total_mw:.4e} mW")
    return "\n".join(lines) + "\n"


_SA_RPT = "Annotated cell percentage = 95.00%\nSAIF time interval = 0 to 1000 ns\n"
_VCS_LOG = "Chronologic VCS simulator copyright ...\nVersion L-2016.06_Full64\n"


def _make_workdir(tmp_path, scenarios, sizes, flats):
    """sizes: {id:int saif bytes}.  flats: {id: power_flat text, or None to omit the file}."""
    wd = tmp_path / "wd"
    (wd / "saif").mkdir(parents=True)
    (wd / "gls-compile-log.txt").write_text(_VCS_LOG)
    for s in scenarios:
        sid = s["id"]
        if sizes.get(sid, 0) > 0:
            (wd / "saif" / f"{sid}.saif").write_bytes(b"x" * sizes[sid])
        rdir = wd / "reports_ptpx" / sid
        rdir.mkdir(parents=True)
        if flats.get(sid) is not None:
            (rdir / "power_flat.rpt").write_text(flats[sid])
        (rdir / "switching_activity.rpt").write_text(_SA_RPT)
    plan = tmp_path / "plan.json"
    plan.write_text(_json.dumps({"power_scenarios": scenarios}))
    return wd, plan


_SCEN = [
    {
        "id": "S1",
        "sequence_ref": "idle_seq",
        "corner_intent": "TT@25C",
        "duration_cycles": 1000,
    },
    {
        "id": "S2",
        "sequence_ref": "busy_seq",
        "corner_intent": "TT@25C",
        "duration_cycles": 5000,
    },
]


def test_run_pass_within_targets(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN,
        sizes={"S1": 2000, "S2": 4000},
        flats={
            "S1": _flat_rpt(0.42, 0.05, 0.02, 0.35),
            "S2": _flat_rpt(1.10, 0.45, 0.55, 0.10),
        },
    )
    out = tmp_path / "power-actual.json"
    rc = p.run(plan, wd, _json.dumps([{"dim": "power_mw", "target": 1.2}]), out)
    assert rc == 0
    data = _json.loads(out.read_text())
    assert data["verdict"] == "pass"
    assert data["violations"] == []
    assert (
        len(data["saif_artifacts"])
        == len(data["ppa_actual"])
        == len(data["power_by_corner"])
        == 2
    )
    assert data["compile_info"] == {"vcs_version": "L-2016.06_Full64"}
    assert "failure_kind" not in data


def test_run_ppa_miss_is_exit0_fail(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN,
        sizes={"S1": 2000, "S2": 4000},
        flats={
            "S1": _flat_rpt(0.42, 0.05, 0.02, 0.35),
            "S2": _flat_rpt(1.85, 0.62, 0.95, 0.28),
        },
    )
    out = tmp_path / "power-actual.json"
    rc = p.run(
        plan,
        wd,
        _json.dumps([{"dim": "power_mw", "target": 1.2, "scenario_id": "S2"}]),
        out,
    )
    assert rc == 0
    data = _json.loads(out.read_text())
    assert data["verdict"] == "fail" and data["failure_kind"] == "ppa"
    assert data["violations"] == [
        {
            "dim": "power_mw",
            "target": 1.2,
            "actual": pytest.approx(1.85),
            "scenario_id": "S2",
        }
    ]


def test_run_empty_targets_sets_gate_skipped(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    out = tmp_path / "power-actual.json"
    rc = p.run(plan, wd, "[]", out)
    assert rc == 0
    data = _json.loads(out.read_text())
    assert data["verdict"] == "pass" and data["ppa_gate_skipped"] is True
    assert data["ppa_actual"][0]["value"] == pytest.approx(0.42)


def test_run_saif_empty_nulls_value_and_excludes(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 0},  # no saif file
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )  # flat parses fine
    out = tmp_path / "power-actual.json"
    rc = p.run(plan, wd, "[]", out)
    assert rc != 0
    assert "FAIL=saif_empty:S1" in capsys.readouterr().err
    data = _json.loads(out.read_text())
    assert data["failure_kind"] == "tooling"
    assert data["failures"][0]["category"] == "saif_dump"
    assert (
        data["failures"][0]["phase"] == "run"
    )  # D: SAIF is a run product (no separate saif phase)
    assert data["ppa_actual"][0]["value"] is None  # P1: nulled despite parseable flat
    assert data["power_by_corner"][0]["power_mw"] is None
    assert all(a["id"] != "S1" for a in data["saif_artifacts"])


def test_run_report_missing_token(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path, _SCEN[:1], sizes={"S1": 2000}, flats={"S1": None}
    )  # power_flat.rpt absent
    out = tmp_path / "power-actual.json"
    rc = p.run(plan, wd, "[]", out)
    assert rc != 0
    assert "FAIL=report_missing:S1" in capsys.readouterr().err  # P5
    assert _json.loads(out.read_text())["ppa_actual"][0]["value"] is None


def test_run_unparseable_total_token(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path, _SCEN[:1], sizes={"S1": 2000}, flats={"S1": "no power numbers here\n"}
    )
    out = tmp_path / "power-actual.json"
    rc = p.run(plan, wd, "[]", out)
    assert rc != 0
    assert "FAIL=unparseable:S1" in capsys.readouterr().err
    assert _json.loads(out.read_text())["ppa_actual"][0]["value"] is None


def test_run_three_component_invariant_break(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(9.99, 0.05, 0.02, 0.35)},
    )  # total != sum
    out = tmp_path / "power-actual.json"
    rc = p.run(plan, wd, "[]", out)
    assert rc != 0
    assert "FAIL=invariant" in capsys.readouterr().err


def test_run_unlinks_stale_out(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    out = tmp_path / "power-actual.json"
    out.write_text("STALE")
    p.run(plan, wd, "[]", out)
    assert "STALE" not in out.read_text()
