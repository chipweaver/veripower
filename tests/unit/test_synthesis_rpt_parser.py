"""Tests for skills/synthesis/scripts/synthesis_rpt_parser.py (grounded format).

Fixtures excerpted from the real Synopsys DC L-2016.03-SP1 sdc_controller corpus:
area.rpt (one 'Total cell area:' summary; a separate 'Total area: undefined' line)
and qor.rpt (one 'Critical Path Slack:' per Timing Path Group block + a design
'WNS / Number of Violating Paths' summary).
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "synthesis" / "scripts"))

import synthesis_rpt_parser as sp  # noqa: E402

# ── fixtures (faithful real-format excerpts) ─────────────────────────────────
SAMPLE_AREA = """\
****************************************
Report : area
Design : sdc_controller
Version: L-2016.03-SP1
****************************************

Combinational area:              17971.632398
Buf/Inv area:                     1052.755235
Noncombinational area:           47046.586865
Macro/Black Box area:                0.000000
Net Interconnect area:      undefined  (No wire load specified)

Total cell area:                 65018.219263
Total area:                 undefined
"""

# No 'Total cell area' anchor (only the 'Total area: undefined' line).
AREA_NO_TOTAL = """\
****************************************
Report : area
****************************************
Combinational area:              17971.632398
Total area:                 undefined
"""

# Two clock groups: 16.99 listed FIRST, 0.95 second. Worst (min) = 0.95.
SAMPLE_QOR = """\
****************************************
Report : qor
Design : sdc_controller
Version: L-2016.03-SP1
****************************************

  Timing Path Group 'sd_clk_o'
  -----------------------------------
  Levels of Logic:              16.00
  Critical Path Length:          2.43
  Critical Path Slack:          16.99
  Critical Path Clk Period:     20.00
  Total Negative Slack:          0.00
  No. of Violating Paths:        0.00
  -----------------------------------

  Timing Path Group 'wb_clk_i'
  -----------------------------------
  Levels of Logic:              31.00
  Critical Path Length:          5.85
  Critical Path Slack:           0.95
  Critical Path Clk Period:     10.00
  Total Negative Slack:          0.00
  No. of Violating Paths:        0.00
  -----------------------------------

  Design  WNS: 0.00  TNS: 0.00  Number of Violating Paths: 0

  Design (Hold)  WNS: 0.00  TNS: 0.00  Number of Violating Paths: 0
"""

# A real violation: negative slack, summary consistently shows the violation.
QOR_VIOLATED = """\
  Timing Path Group 'wb_clk_i'
  -----------------------------------
  Critical Path Slack:          -0.50
  Critical Path Clk Period:     10.00
  Total Negative Slack:         -0.50
  No. of Violating Paths:        3.00
  -----------------------------------

  Design  WNS: -0.50  TNS: -0.50  Number of Violating Paths: 3
"""

# Self-contradiction: negative per-group slack, but the design summary is clean.
QOR_CONTRADICT = """\
  Timing Path Group 'wb_clk_i'
  -----------------------------------
  Critical Path Slack:          -0.50
  -----------------------------------

  Design  WNS: 0.00  TNS: 0.00  Number of Violating Paths: 0
"""

# No 'Critical Path Slack' anchor at all.
QOR_NO_GROUP = """\
****************************************
Report : qor
****************************************
  Cell Count
  Leaf Cell Count:               6640
"""


def _stage(tmp_path, area=SAMPLE_AREA, qor=SAMPLE_QOR):
    """Write reports/{area,qor}.rpt under tmp_path; return (reports_dir, out_path)."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "area.rpt").write_text(area)
    (reports / "qor.rpt").write_text(qor)
    return reports, tmp_path / "ppa-actual.json"


# ── parsing units ────────────────────────────────────────────────────────────
def test_parse_area_total_cell_area():
    assert sp.parse_area_um2(SAMPLE_AREA) == pytest.approx(65018.219263)


def test_parse_area_ignores_total_area_undefined():
    # 'Total area: undefined' must NOT be picked up; only 'Total cell area'.
    assert sp.parse_area_um2(AREA_NO_TOTAL) is None


def test_parse_worst_slack_is_min_across_groups_not_first():
    # THE regression: worst = 0.95 (wb_clk_i), NOT 16.99 (sd_clk_o, listed first).
    assert sp.parse_worst_slack_ns(SAMPLE_QOR) == pytest.approx(0.95)
    assert sp.parse_worst_slack_ns(SAMPLE_QOR) != pytest.approx(16.99)


def test_parse_worst_slack_none_when_absent():
    assert sp.parse_worst_slack_ns(QOR_NO_GROUP) is None


def test_parse_wns_summary_setup_not_hold():
    # Matches the setup 'Design  WNS:' line, not 'Design (Hold)  WNS:'.
    assert sp.parse_wns_summary(SAMPLE_QOR) == {"wns": 0.0, "violating_paths": 0}
    assert sp.parse_wns_summary(QOR_VIOLATED) == {"wns": -0.5, "violating_paths": 3}


def test_main_rejects_bad_arg_exit2():
    assert sp.main(["synthesis_rpt_parser.py"]) == 2


# ── run() exit-code contract ──────────────────────────────────────────────────
def test_run_slack_min_regression(tmp_path):
    reports, out = _stage(tmp_path)
    assert sp.run(reports, out, None, None) == 0
    data = json.loads(out.read_text())
    slack = [a for a in data["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(0.95)
    assert slack["value"] != pytest.approx(16.99)


def test_run_area_disambiguation(tmp_path):
    reports, out = _stage(tmp_path)
    assert sp.run(reports, out, None, None) == 0
    data = json.loads(out.read_text())
    area = [a for a in data["ppa_actual"] if a["dim"] == "area_um2"][0]
    assert area["value"] == pytest.approx(65018.219263)


def test_run_verdict_pass(tmp_path):
    reports, out = _stage(tmp_path)
    assert sp.run(reports, out, 70000.0, 0.5) == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "pass"
    assert data["violations"] == []


def test_run_verdict_fail_ppa_exit0(tmp_path):
    reports, out = _stage(tmp_path)
    assert sp.run(reports, out, None, 2.0) == 0  # PPA miss is still exit 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "fail"
    assert data["violations"] == [
        {"dim": "timing_slack_ns", "target": 2.0, "actual": pytest.approx(0.95)}
    ]


def test_run_no_targets_vacuous_pass(tmp_path):
    reports, out = _stage(tmp_path)
    assert sp.run(reports, out, None, None) == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "pass"
    assert data["violations"] == []


def test_run_violated_slack(tmp_path):
    reports, out = _stage(tmp_path, qor=QOR_VIOLATED)
    assert sp.run(reports, out, None, 0.0) == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "fail"
    slack = [a for a in data["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(-0.5)


def test_run_unparseable_area_exit3(tmp_path):
    reports, out = _stage(tmp_path, area=AREA_NO_TOTAL)
    assert sp.run(reports, out, None, None) == 3
    assert not out.exists()


def test_run_unparseable_qor_exit3(tmp_path):
    reports, out = _stage(tmp_path, qor=QOR_NO_GROUP)
    assert sp.run(reports, out, None, None) == 3
    assert not out.exists()


def test_run_missing_report_exit1(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    assert sp.run(reports, tmp_path / "ppa-actual.json", None, None) == 1


def test_run_removes_stale_on_failure(tmp_path):
    reports, out = _stage(tmp_path)
    assert sp.run(reports, out, None, None) == 0
    assert out.exists()
    # now corrupt the area report and re-run -> exit 3, stale out gone
    (reports / "area.rpt").write_text(AREA_NO_TOTAL)
    assert sp.run(reports, out, None, None) == 3
    assert not out.exists()


def test_run_wns_cross_check_contradiction_exit3(tmp_path):
    # negative per-group slack but a clean design summary -> exit 3 (review S3)
    reports, out = _stage(tmp_path, qor=QOR_CONTRADICT)
    assert sp.run(reports, out, None, None) == 3
    assert not out.exists()


# ── finalize / build_result (v4 stage-CLI-tool) ───────────────────────────────
def _workdir(tmp_path, area=SAMPLE_AREA, qor=SAMPLE_QOR):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "area.rpt").write_text(area)
    (reports / "qor.rpt").write_text(qor)
    return tmp_path


def test_build_result_pass_lean_shape(tmp_path):
    wd = _workdir(tmp_path)
    assert (
        sp.build_result(
            wd, module="tpu_top", top="tpu_top", area_target=None, slack_target=None
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "synthesis",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    slack = [a for a in ss["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(0.95)  # parser regression: min across groups
    assert ss["violations"] == [] and ss["ppa_targets"] == []
    assert (
        "notes" not in ss and "power_report" not in ss
    )  # lean shape: dropped fields absent
    assert "rtl_filelist" not in ss and "timing_exceptions" not in ss


def test_build_result_tooling_fail_on_unparseable(tmp_path):
    wd = _workdir(tmp_path, area=AREA_NO_TOTAL)  # parser run() returns 3
    assert (
        sp.build_result(
            wd, module="tpu_top", top="tpu_top", area_target=None, slack_target=None
        )
        == 0
    )
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert (
        ss["failure_kind"] == "tooling"
        and ss["fail_reason"] == "synthesis report unparseable"
    )


def test_finalize_cli_does_not_break_legacy_parse_cli(tmp_path):
    # the legacy bare-flag invocation still parses (no subcommand) — back-compat guard
    reports = _workdir(tmp_path) / "reports"
    out = tmp_path / "ppa-actual.json"
    assert (
        sp.main(
            [
                "synthesis_rpt_parser.py",
                "--reports-dir",
                str(reports),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert json.loads(out.read_text())["verdict"] == "pass"


# ── reproducibility-header derivations (tool / lib_db / clock) ────────────────
def test_parse_tool_from_report_version():
    assert sp.parse_tool("Version: L-2016.03-SP1\n") == "Design Compiler L-2016.03-SP1"
    assert sp.parse_tool("no version here") == "Design Compiler unknown"


def test_read_lib_db_from_config_tcl(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "config.tcl").write_text(
        'set ::env(LIB_DB) "/home/eda/Foundry/TSMC.90/slow.db"\n'
    )
    assert sp.read_lib_db(tmp_path) == "/home/eda/Foundry/TSMC.90/slow.db"
    assert sp.read_lib_db(tmp_path / "nope") is None


def test_parse_clock_from_sdc(tmp_path):
    (tmp_path / "constraints.sdc").write_text(
        "create_clock -name i_clk -period 10.0 [get_ports i_clk]\n"
    )
    assert sp.parse_clock(tmp_path) == {"name": "i_clk", "period_ns": 10.0}
