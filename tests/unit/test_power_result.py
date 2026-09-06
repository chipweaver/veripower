"""Tests for skills/power-analysis/scripts/power/result.py"""

import json as _json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "power-analysis" / "scripts"))

from power import result as p  # noqa: E402
from power.result import parse_total_power_mw  # noqa: E402

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


# ── annotation rate ──
# A parser of vendor output is only tested once it has met vendor output — hand-written text
# can be invented to match whatever the regex happens to want. Hence the first test below runs
# on the committed real report.

_SAIF_IDLE = REPO_ROOT / "tests/unit/fixtures/power-golden/saif-excerpts/idle.saif"
_SAIF_ACTIVE = REPO_ROOT / "tests/unit/fixtures/power-golden/saif-excerpts/active.saif"


def test_toggled_fraction_separates_a_run_that_moved_from_one_that_did_not():
    # Both excerpts are verbatim VCS $toggle_report output from the same design and the
    # same testbench, 40 nets each: one scenario drove it, the other left it sitting.
    # Neither PT report distinguishes them — report_switching_activity is byte-identical
    # for the two, because 0% and 100% of nothing both annotate perfectly.
    assert p.parse_toggled_net_fraction(_SAIF_IDLE) == 0.0
    assert p.parse_toggled_net_fraction(_SAIF_ACTIVE) == pytest.approx(35 / 40)


def test_toggled_fraction_none_when_absent_or_carrying_no_counts(tmp_path):
    # A SAIF with no TC entry at all is a format surprise, not a design that sat still —
    # reporting 0.0 there would put a made-up qualification on the power number.
    assert p.parse_toggled_net_fraction(tmp_path / "nope.saif") is None
    stub = tmp_path / "stub.saif"
    stub.write_text('(SAIFILE (SAIFVERSION "2.0"))\n')
    assert p.parse_toggled_net_fraction(stub) is None


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


# ptpx.tcl writes this per scenario and its own in-run 0%-annotation gate reads it; the
# whole reports_ptpx/ tree is promoted, so a workdir without it is not shaped like a run.
_SA_RPT = (
    ' Switching Activity Overview Statistics for "top"\n'
    " Nets             95(95.00%)   5(5.00%)   100\n"
)
_VCS_LOG = "Chronologic VCS simulator copyright ...\nVersion L-2016.06_Full64\n"


def _make_workdir(tmp_path, scenarios, sizes, flats, statuses=None):
    """sizes: {id: 0 to omit the SAIF, non-zero to write one}. A written SAIF is the real
    excerpt whose 40 nets carry 35 toggles, so the scenario table's toggled_net_fraction
    comes out of the same parser a run uses.  flats: {id: power_flat text, or None to omit
    the file}.  statuses: {id: token, or None to omit the file}; unnamed scenarios pass."""
    wd = tmp_path / "wd"
    (wd / "saif").mkdir(parents=True)
    (wd / "gls-compile-log.txt").write_text(_VCS_LOG)
    for s in scenarios:
        sid = s["id"]
        if sizes.get(sid, 0) > 0:
            (wd / "saif" / f"{sid}.saif").write_bytes(_SAIF_ACTIVE.read_bytes())
        token = (statuses or {}).get(sid, "PASS")
        if token is not None:
            (wd / "saif" / f"{sid}.status").write_text(token + "\n")
        rdir = wd / "reports_ptpx" / sid
        rdir.mkdir(parents=True)
        if flats.get(sid) is not None:
            (rdir / "power_flat.rpt").write_text(flats[sid])
        (rdir / "switching_activity.rpt").write_text(_SA_RPT)
    plan = tmp_path / "plan"  # the simulation-plan workdir, as injected
    plan.mkdir(exist_ok=True)
    (plan / "power-scenarios.json").write_text(_json.dumps(scenarios))
    return wd, plan


def _bound(rid, op, value, scenario=None, judge="power-analysis"):
    t = {"dim": "power_mw", "op": op, "value": value}
    if scenario:
        t["scenario"] = scenario
    return {
        "id": rid,
        "verbatim": f"power {op} {value} mW",
        "judge": judge,
        "target": t,
    }


def _spec(tmp_path, rows):
    sd = tmp_path / "spec"
    sd.mkdir(exist_ok=True)
    (sd / "requirements.json").write_text(_json.dumps(rows))
    return sd


_SCEN = [
    {
        "id": "S1",
        "sequence_ref": "idle_seq",
    },
    {
        "id": "S2",
        "sequence_ref": "busy_seq",
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
    rc, data = p.run(plan, wd, [_bound("R-P", "<=", 1.2)])
    assert rc == 0
    # no scenario named: the bound holds for every scenario, and actual is the worst of them
    assert data["requirements"] == [
        {
            "id": "R-P",
            "met": True,
            "actual": pytest.approx(1.10),
            "measured": "worst power_mw across 2 scenarios: "
            "reports_ptpx/S1/power_flat.rpt, reports_ptpx/S2/power_flat.rpt",
        }
    ]
    assert (
        len(data["saif_artifacts"])
        == len(data["measurements"])
        == len(data["power_by_scenario"])
        == 2
    )
    assert data["compile_info"] == {"vcs_version": "L-2016.06_Full64"}
    # The field that qualifies power_mw must survive the whole run, not just the parser.
    assert [c["toggled_net_fraction"] for c in data["power_by_scenario"]] == [
        pytest.approx(35 / 40),
        pytest.approx(35 / 40),
    ]


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
    rc, data = p.run(plan, wd, [_bound("R-P", "<=", 1.2, scenario="S2")])
    assert rc == 0  # a miss is a verdict, not a tooling failure
    assert data["requirements"] == [
        {
            "id": "R-P",
            "met": False,
            "actual": pytest.approx(1.85),
            "measured": "power_mw from reports_ptpx/S2/power_flat.rpt",
        }
    ]


def test_run_a_bound_naming_an_unmeasured_scenario_cannot_be_judged(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    with pytest.raises(ValueError, match="S9"):
        p.run(plan, wd, [_bound("R-P", "<=", 1.2, scenario="S9")])


def test_run_no_targeted_rows_judges_nothing_but_still_measures(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    rc, data = p.run(plan, wd, [])
    assert rc == 0
    assert data["requirements"] == []
    assert data["measurements"][0]["value"] == pytest.approx(0.42)


def test_run_saif_empty_nulls_value_and_excludes(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 0},  # no saif file
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )  # flat parses fine
    rc, data = p.run(plan, wd, [])
    assert rc != 0
    assert "FAIL=saif_empty:S1" in capsys.readouterr().err
    assert data["failures"][0]["category"] == "saif_dump"
    assert (
        data["failures"][0]["phase"] == "run"
    )  # D: SAIF is a run product (no separate saif phase)
    assert data["measurements"][0]["value"] is None  # nulled despite parseable flat
    assert data["power_by_scenario"][0]["power_mw"] is None
    assert all(a["id"] != "S1" for a in data["saif_artifacts"])


def test_run_gls_uvm_failure_nulls_the_power_number(tmp_path, capsys):
    """The gate-level run is the only functional evidence this stage produces, and it is also
    what the SAIF is a recording of: activity dumped from a run whose stimulus reported errors
    does not qualify a power number, however cleanly PT-PX parses."""
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN,
        sizes={"S1": 2000, "S2": 4000},
        flats={
            "S1": _flat_rpt(0.42, 0.05, 0.02, 0.35),
            "S2": _flat_rpt(1.10, 0.45, 0.55, 0.10),
        },
        statuses={"S1": "FAIL"},  # S2 passes
    )
    rc, data = p.run(plan, wd, [_bound("R-P", "<=", 1.2)])
    assert rc != 0
    assert "FAIL=gls_uvm:S1" in capsys.readouterr().err
    f0 = data["failures"][0]
    assert (f0["id"], f0["category"], f0["phase"]) == ("S1", "gls_uvm", "run")
    assert f0["log_excerpt"] == "saif/S1.run.log"
    assert data["power_by_scenario"][0]["power_mw"] is None
    assert (
        data["power_by_scenario"][1]["power_mw"] == 1.10
    )  # the passing scenario stands


def test_run_missing_gls_status_is_not_a_pass(tmp_path):
    """A run that hit $fatal or died never reached report_phase, so it leaves no verdict — and
    the simulator's exit code cannot fill that in. Absence fails the scenario."""
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
        statuses={"S1": None},  # never written
    )
    rc, data = p.run(plan, wd, [])
    assert rc != 0
    assert data["failures"][0]["category"] == "gls_uvm"
    assert "absent" in data["failures"][0]["error_summary"]
    assert data["measurements"][0]["value"] is None


def test_run_report_missing_token(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path, _SCEN[:1], sizes={"S1": 2000}, flats={"S1": None}
    )  # power_flat.rpt absent
    rc, data = p.run(plan, wd, [])
    assert rc != 0
    assert "FAIL=report_missing:S1" in capsys.readouterr().err
    assert data["measurements"][0]["value"] is None


def test_run_unparseable_total_token(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path, _SCEN[:1], sizes={"S1": 2000}, flats={"S1": "no power numbers here\n"}
    )
    rc, data = p.run(plan, wd, [])
    assert rc != 0
    assert "FAIL=unparseable:S1" in capsys.readouterr().err
    assert data["measurements"][0]["value"] is None


def test_run_three_component_invariant_break(tmp_path, capsys):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(9.99, 0.05, 0.02, 0.35)},
    )  # total != sum
    rc, data = p.run(plan, wd, [])
    assert rc != 0
    assert "FAIL=invariant" in capsys.readouterr().err


def test_run_returns_a_payload_on_both_exit_paths(tmp_path):
    # was "unlinks the stale sidecar". There is no file to go stale; what build_result needs is
    # that the payload comes back on the data-failure path too, since it folds either way.
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    rc, data = p.run(plan, wd, [])
    assert rc == 0 and data["requirements"] == []
    wd_bad, plan_bad = _make_workdir(
        tmp_path / "bad", _SCEN[:1], sizes={"S1": 0}, flats={}
    )
    rc, data = p.run(plan_bad, wd_bad, "[]")
    assert rc != 0 and data["failures"]  # the fold source exists on the failure path


# ── invariant tolerance ───────────────────────────────────────────────────────


def test_invariant_tolerates_4sigfig_rounding(tmp_path):
    # Real PrimeTime PX format: "Dynamic Power Units = 1 W" (no inline unit on summary lines).
    # Values are in W; _resolve_mw converts to mW (multiply by 1000).
    # After conversion: Total=1.653 mW, sum=1.652940 mW, diff=6.0e-5 mW.
    # 6.0e-5 > _EPS_MW (1e-6) → trips the invariant AS-IS, but << 1% of total → must NOT flag.
    wd = tmp_path / "wd"
    (wd / "saif").mkdir(parents=True)
    (wd / "saif" / "S1.saif").write_text("x" * 100)
    (wd / "saif" / "S1.status").write_text("PASS\n")
    rdir = wd / "reports_ptpx" / "S1"
    rdir.mkdir(parents=True)
    (rdir / "power_flat.rpt").write_text(
        # Header declares units = 1 W (no inline unit on summary lines, parser uses header)
        "Dynamic Power Units = 1 W\nLeakage Power Units = 1 W\n"
        "Cell Internal Power  = 1.300e-03\n"  # 1.300e-03 W = 1.300 mW
        "Net Switching Power  = 3.029e-04\n"  # 3.029e-04 W = 0.3029 mW
        "Cell Leakage Power   = 5.000e-05\n"  # 5.000e-05 W = 0.05000 mW
        "Total Power          = 1.653e-03\n"  # 1.653e-03 W = 1.653 mW; sum=1.65290 mW, diff=6.0e-5
    )
    (rdir / "switching_activity.rpt").write_text("")
    (wd / "gls-compile-log.txt").write_text("VCS L-2016.06_Full64\n")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "power-scenarios.json").write_text(
        _json.dumps(
            [
                {
                    "id": "S1",
                    "sequence_ref": "idle_seq",
                }
            ]
        )
    )
    rc, data = p.run(plan, wd, [])
    # Before the fix: rc==1, failures[0].category=="ptpx_data" (invariant). After: clean pass.
    assert rc == 0, (
        f"4-sig-fig rounding must not trip the invariant; failures={data.get('failures')}"
    )
    assert data["requirements"] == []
    assert data["failures"] == []


# ── build_result + finalize subcommand ────────────────────────────────────────


def test_build_result_pass_lean_shape(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    assert p.build_result(wd, str(plan), [], []) == 0
    env = _json.loads((wd / "result.json").read_text())
    assert env["stage"] == "power-analysis"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert "verdict" not in ss and "violations" not in ss
    assert (
        ss["requirements"] == []
    )  # no row judged by this stage; the empty list says so
    assert ss["compile_info"]["vcs_version"] == "L-2016.06_Full64"
    assert "notes" not in ss  # lean shape: dropped field absent


def test_build_result_tooling_fail_on_invariant(tmp_path):
    # A report whose Total != sum(components) by >> 1% (the parser's invariant)
    # -> parser exit 1 -> build_result writes fail_reason + failures[].
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(9.99, 0.05, 0.02, 0.35)},
    )  # deliberately off
    assert p.build_result(wd, str(plan), [], []) == 0
    ss = _json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["failures"] and ss["failures"][0]["category"] == "ptpx_data"
    assert isinstance(ss["fail_reason"], str) and ss["fail_reason"]


def test_build_result_missed_row(tmp_path):
    # a scenario over the engineer's bound -> status=fail + requirements
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN,
        sizes={"S1": 2000, "S2": 4000},
        flats={
            "S1": _flat_rpt(0.42, 0.05, 0.02, 0.35),
            "S2": _flat_rpt(1.85, 0.62, 0.95, 0.28),
        },
    )
    assert (
        p.build_result(wd, str(plan), [_bound("R-P", "<=", 1.2, scenario="S2")], [])
        == 0
    )
    ss = _json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["requirements"] == [
        {
            "id": "R-P",
            "met": False,
            "actual": pytest.approx(1.85),
            "measured": "power_mw from reports_ptpx/S2/power_flat.rpt",
        }
    ]
    assert all(v["measured"] for v in ss["requirements"])  # each names its own
    assert ss["fail_reason"] == "requirement(s) not met: R-P"


def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps build_result: any internal raise -> exit 2 (BLOCKED), never
    # status=fail. (The old main() finalize branch had this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(p, "build_result", boom)
    assert p.finalize(tmp_path, "scaffold.json", [], []) == 2


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    MAIN = REPO_ROOT / "skills/power-analysis/scripts/power/__main__.py"
    # --workdir is the one flag finalize cannot infer; omitting it is argparse exit 2,
    # never a written envelope.
    r = subprocess.run(
        ["python3", str(MAIN), "finalize"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert not (tmp_path / "result.json").exists()


def test_finalize_cli_happy_path(tmp_path):
    # End-to-end through _cmd_finalize (lazy handler import + the dispatch.json read
    # + the ledger read), not just in-process build_result. A handler typo
    # would pass every other test (which call build_result directly) but fail here.
    # finalize reads the ledger via the injected dispatch.json "requirements" key.
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    spec = _spec(tmp_path, [])
    (wd / "dispatch.json").write_text(
        _json.dumps({"inputs": {"requirements": str(spec), "scaffold": str(plan)}})
    )
    MAIN = REPO_ROOT / "skills/power-analysis/scripts/power/__main__.py"
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = _json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"]) == ("power-analysis", "pass")


# ── the ledger, read from the injected dispatch.json "requirements" stage root ──
def test_finalize_cli_reads_the_ledger(tmp_path):
    # finalize reads the rows power-analysis judges straight from the specification
    # stage root's requirements.json, whose location comes from the injected dispatch.json.
    module_root = tmp_path / "asic" / "dut_top"
    wd, plan = _make_workdir(
        module_root / "Verification" / "power-analysis" / "runs",
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    spec_dir = module_root / "Design" / "specification"
    spec_dir.mkdir(parents=True)
    (spec_dir / "requirements.json").write_text(
        _json.dumps(
            [
                _bound("R-P", "<", 0.1, scenario="S1"),  # unreachable -> forces a fail
                {  # synthesis judges this one -> not ours
                    "id": "R-A",
                    "verbatim": "area",
                    "judge": "synthesis",
                    "target": {"dim": "area_um2", "op": "<=", "value": 999.0},
                },
                {
                    "id": "R-R",
                    "verbatim": "power reported only",
                    "judge": "power-analysis",
                },
            ]
        )
    )
    (wd / "dispatch.json").write_text(
        _json.dumps({"inputs": {"requirements": str(spec_dir), "scaffold": str(plan)}})
    )
    MAIN = REPO_ROOT / "skills/power-analysis/scripts/power/__main__.py"
    declared = _json.dumps(
        [
            {
                "id": "R-R",
                "met": True,
                "actual": "0.42 mW reported",
                "measured": "reports_ptpx/S1/power_flat.rpt, read by hand",
            }
        ]
    )
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--requirements",
            declared,
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = _json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert ss["requirements"] == [
        {
            "id": "R-P",
            "met": False,
            "actual": pytest.approx(0.42),
            "measured": "power_mw from reports_ptpx/S1/power_flat.rpt",
        },
        {
            "id": "R-R",
            "met": True,
            "actual": "0.42 mW reported",
            "measured": "reports_ptpx/S1/power_flat.rpt, read by hand",
        },
    ]
    assert ss["fail_reason"] == "requirement(s) not met: R-P"

    # the undeclared row blocks: a verdict nobody gave cannot pass as silence
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2 and "R-R" in r.stderr


# ── artifacts[] enumeration ───────────────────────────────────────────────────


def test_enumerate_artifacts_present_only_no_self(tmp_path):
    wd = tmp_path / "wd"
    wd.mkdir()
    # present files + dirs
    for f in [
        "env.sh",
        "Makefile",
        "README.md",
        "tb_filelist_abs.f",
        "simv",
        "gls-compile-log.txt",
        "gls-run-log.txt",
        "ptpx.log",
        "make.out",
    ]:
        (wd / f).write_text("x")
    for d in ["scripts", "scaffold", "simv.daidir", "saif", "reports_ptpx"]:
        (wd / d).mkdir()
    (wd / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in p.enumerate_artifacts(wd)]
    # what this run produced or resolved
    for expect in [
        "env.sh",
        "scaffold",
        "tb_filelist_abs.f",
        "saif",
        "reports_ptpx",
        "gls-compile-log.txt",
    ]:
        assert expect in paths
    # what the skill shipped, or what a rebuild reproduces, or a log's second copy
    for absent in [
        "Makefile",
        "README.md",
        "scripts",
        "simv",
        "simv.daidir",
        "make.out",
    ]:
        assert absent not in paths, f"{absent} is on disk but must not be promoted"
    assert "result.json" not in paths
    assert all((wd / pth).exists() for pth in paths)  # only present paths (file OR dir)


# ── Golden test against a real run ────────────────────────────────────────────


def _copy_golden(tmp_path, root):
    """The captured workdir plus the per-scenario verdicts. The capture predates the file
    base_test writes, and a run's own output is not something to hand-author into the
    fixture, so the passing token is supplied here."""
    import shutil

    wd = tmp_path / "wd"
    shutil.copytree(root / "real", wd)
    for saif in (wd / "saif").glob("*.saif"):
        saif.with_suffix(".status").write_text("PASS\n")
    return wd


def test_golden_real_reports_lean_pass(tmp_path):
    ROOT = Path(__file__).resolve().parent / "fixtures" / "power-golden"
    wd = _copy_golden(tmp_path, ROOT)
    rc = p.build_result(wd, str(ROOT / "plan"), [], [])
    assert rc == 0
    env = _json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    # With the invariant tolerance in place, the gate parses the real 4-sig-fig reports clean -> pass.
    assert env["stage"] == "power-analysis"
    assert env["status"] == "pass"
    assert env["produced_at"].endswith("Z")
    # the 7 stage_specific fields fold through verbatim from the clean sidecar (minus verdict)
    assert set(ss) >= {
        "saif_artifacts",
        "compile_info",
        "failures",
        "requirements",
        "power_by_scenario",
    }
    assert "verdict" not in ss and "violations" not in ss
    assert ss["failures"] == []  # clean parse — no ptpx_data failures
    assert ss["requirements"] == []  # no row judged by this stage
    assert ss["compile_info"]["vcs_version"] == "L-2016.06_Full64"
    assert all(v.get("measured") for v in ss["requirements"])  # every scenario parsed
    assert "notes" not in ss  # lean: dropped
    paths = [a["path"] for a in env["artifacts"]]
    assert "reports_ptpx" in paths
    assert "result.json" not in paths


def test_golden_is_schema_valid(tmp_path):
    # Canonical pattern: validate the in-memory dict against {envelope schema + this
    # stage's result.schema} via Registry (mirrors test_signoff_result.py pattern).
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    ROOT = Path(__file__).resolve().parent / "fixtures" / "power-golden"
    wd = _copy_golden(tmp_path, ROOT)
    p.build_result(wd, str(ROOT / "plan"), [], [])
    env = _json.loads((wd / "result.json").read_text())
    env_schema = _json.loads(
        (REPO_ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = _json.loads(
        (REPO_ROOT / "skills/power-analysis/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        "https://veripower.local/schemas/envelope.schema.json",
        Resource.from_contents(env_schema),
    )
    Draft202012Validator(stage_schema, registry=registry).validate(
        env
    )  # raises on invalid


# ── declared failure: the paths where the gate has nothing to read ──────────
#
# Before finalize grew --fail-reason, these two paths (a missing external reference, a
# non-zero `make`) had no verb at all: SKILL.md told the agent to write status=fail by
# hand while the same step forbade hand-assembling the envelope, and an envelope the
# schema rejects reaps as blocked rather than fail, so a hand-written one spent a
# routable failure on a human. These tests hold the verb to being the only writer.


def _declared(tmp_path, **kw):
    wd = tmp_path / "wd"
    wd.mkdir()
    rc = p.build_result(wd, tmp_path / "nonexistent-plan", [], [], **kw)
    return rc, wd


def test_declared_fail_writes_the_envelope_without_touching_the_reports(tmp_path):
    # The workdir holds no reports and the scaffold path does not exist — the state a
    # missing external reference leaves behind. The declaration must precede run(),
    # which would raise on the absent power-scenarios.json.
    rc, wd = _declared(
        tmp_path,
        fail_reason="external reference missing: Design/synthesis/out/dut_top_syn.sdf",
        fix_owner="synthesis",
    )
    assert rc == 0
    env = _json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert ss["fix_owner"] == "synthesis"
    assert "dut_top_syn.sdf" in ss["fail_reason"]
    # The pass-shape is not invented on a run that produced none of it.
    for absent in ("saif_artifacts", "power_by_scenario", "failures"):
        assert absent not in ss


def test_declared_fail_validates_against_the_stage_schema(tmp_path):
    # The defect this whole change exists for: an envelope the schema rejects reaps as
    # `blocked`, so the fix_owner the agent already worked out never reaches the kernel.
    from framework.scripts import facts

    _, wd = _declared(
        tmp_path,
        fail_reason="gls-compile failed: phase=compile, LIB_V not readable",
        fix_owner="simulation",
    )
    env = _json.loads((wd / "result.json").read_text())
    assert facts.validate_result("power-analysis", env) is None


def test_declared_fail_omits_fix_owner_when_the_caller_cannot_name_one(tmp_path):
    _, wd = _declared(tmp_path, fail_reason="pt_shell license checkout failed")
    ss = _json.loads((wd / "result.json").read_text())["stage_specific"]
    assert "fix_owner" not in ss  # an unnamed owner is how a human gets called in


def test_finalize_blocked_on_an_empty_declaration(tmp_path):
    # A declaration with no cause in it is BLOCKED, never status=fail — and BLOCKED
    # writes nothing, so the retry is not looking at a half-declared envelope.
    wd = tmp_path / "wd"
    wd.mkdir()
    assert p.finalize(wd, tmp_path / "plan", [], [], None, "   ") == 2
    assert not (wd / "result.json").exists()


def test_declared_fail_through_the_cli(tmp_path):
    # End-to-end through _cmd_finalize: the flags must reach result.finalize in the
    # right positions. A swapped pair would pass every in-process test above.
    wd = tmp_path / "wd"
    wd.mkdir()
    (wd / "dispatch.json").write_text(
        _json.dumps(
            {
                "inputs": {
                    "requirements": str(_spec(tmp_path, [])),
                    "scaffold": str(tmp_path / "plan"),
                }
            }
        )
    )
    MAIN = REPO_ROOT / "skills/power-analysis/scripts/power/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--fail-reason",
            "ptpx failed: phase=ptpx, read_saif annotated 0%",
            "--fix-owner",
            "simulation-plan",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    ss = _json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fix_owner"] == "simulation-plan"
    assert "annotated 0%" in ss["fail_reason"]


# ── failures[].category has exactly one writer ──────────────────────────────


def test_category_enum_is_exactly_what_the_parser_writes():
    # 386b067 narrowed the enum to what the parser can detect but left the deployed
    # scripts printing `category=sdf` / `category=netlist`, which SKILL.md told the agent
    # to copy verbatim — two values the schema rejects. And `tooling` survived that commit
    # on the strength of a condition the parser has no branch for: nothing in the history
    # ever wrote it. The enum and the parser's literals are now one set.
    import re

    from _skills_sot import load_stage_schema

    schema = load_stage_schema("power-analysis")
    enum = None
    for entry in schema["allOf"]:
        ss = entry.get("properties", {}).get("stage_specific", {})
        f = ss.get("properties", {}).get("failures")
        if f:
            enum = set(f["items"]["properties"]["category"]["enum"])
    src = (REPO_ROOT / "skills/power-analysis/scripts/power/result.py").read_text()
    written = set(re.findall(r'"category":\s*"([a-z_]+)"', src))
    assert enum == written, (
        f"schema enum {sorted(enum)} vs parser writes {sorted(written)}"
    )


def test_no_deployed_script_emits_a_category_for_the_agent_to_transcribe():
    # The agent's failure path is --fail-reason prose now, so a `category=` token in a
    # tool log has no legal destination: transcribing one fails schema validation at reap
    # and lands `blocked` instead of a routable fail. `phase=` stays — it names which make
    # step broke, which the caller carries into the reason sentence.
    tmpl = REPO_ROOT / "skills/power-analysis/templates"
    offenders = [
        f"{f.relative_to(REPO_ROOT)}:{n}"
        for f in sorted(tmpl.rglob("*"))
        if f.is_file() and f.suffix in {".sh", ".tcl", ".py", ".tmpl"}
        for n, line in enumerate(f.read_text().splitlines(), 1)
        if "category=" in line
    ]
    assert not offenders, f"deployed scripts still print a category: {offenders}"
    # and at least one still prints the phase, so the removal did not take both.
    assert any(
        "phase=" in f.read_text()
        for f in tmpl.rglob("*")
        if f.is_file() and f.suffix in {".sh", ".tcl"}
    )
