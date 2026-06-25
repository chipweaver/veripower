"""Tests for skills/timing-analysis/scripts/timing_rpt_parser.py (marker-keyed).

Fixtures are real-format excerpts from the pt2016 (M-2016.12-SP1) sdc_controller
corpus: bare `report_timing -delay max|min` prints the worst path per group, each
block ending in a 'slack (MET)' / 'slack (VIOLATED...)' line; the displayed slack
rounds to report precision, so the MARKER — not the number — decides met/violated.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "timing-analysis" / "scripts"))

import timing_rpt_parser as sp  # noqa: E402

# ── fixtures (faithful real-format excerpts) ─────────────────────────────────
_SETUP_MET = """\
****************************************
Report : timing
\t-path_type full
\t-delay_type max
\t-max_paths 1
\t-sort_by slack
Design : sdc_controller
Version: M-2016.12-SP1
****************************************


  Startpoint: wb_adr_i[6]
               (input port clocked by wb_clk_i)
  Endpoint: wb_dat_o[2]
               (output port clocked by wb_clk_i)
  Path Group: wb_clk_i
  Path Type: max

  data arrival time                                   3.87
  data required time                                  6.80
  ---------------------------------------------------------------
  slack (MET)                                         2.93

"""

_HOLD_MET = """\
****************************************
Report : timing
\t-delay_type min
\t-max_paths 1
\t-sort_by slack
Design : sdc_controller
Version: M-2016.12-SP1
****************************************


  Startpoint: data_master/a_cmp_rx_r_reg
               (rising edge-triggered flip-flop clocked by wb_clk_i)
  Endpoint: data_master/a_cmp_rx_r_reg
               (rising edge-triggered flip-flop clocked by wb_clk_i)
  Path Group: wb_clk_i
  Path Type: min

  slack (MET)                                         0.20

"""

# Real F1 case: displayed slack is 0.00 but the path is VIOLATED.
_HOLD_VIOLATED_ZERO = """\
****************************************
Report : timing
\t-delay_type min
\t-max_paths 1
\t-sort_by slack
Design : sdc_controller
Version: M-2016.12-SP1
****************************************


  Startpoint: u_rx_filler/wb_free_reg
               (rising edge-triggered flip-flop clocked by wb_clk_i)
  Endpoint: u_rx_filler/rd_reg
               (rising edge-triggered flip-flop clocked by wb_clk_i)
  Path Group: wb_clk_i
  Path Type: min

  slack (VIOLATED: increase significant digits)       0.00

"""

# significant_digits=4 case: the same path prints a real negative number.
# (re.sub, not .replace, so a whitespace mismatch fails loudly instead of no-op'ing.)
_HOLD_VIOLATED_NEG = re.sub(
    r"slack \(VIOLATED[^)]*\)\s+0\.00",
    "slack (VIOLATED)                                    -0.0050",
    _HOLD_VIOLATED_ZERO,
)

_CHECK_TIMING = """\
Information: Checking 'unconstrained_endpoints'.
Warning: There are 1461 endpoints which are not constrained for maximum delay.

Information: Checking 'no_clock'.
Warning: There are 756 register clock pins with no clock.

check_timing succeeded.
"""

_CHECK_TIMING_CLEAN = """\
Information: Checking 'unconstrained_endpoints'.
Information: Checking 'no_clock'.
check_timing succeeded.
"""


def _write(tmp_path, text):
    rep = tmp_path / "timing-report.txt"
    rep.write_text(text)
    return rep, tmp_path / "timing-actual.json"


# ── parse-unit tests ─────────────────────────────────────────────────────────
def test_parse_direction_met():
    d = sp.parse_direction(_SETUP_MET + _HOLD_MET, "max")
    assert d["met"] is True
    assert d["worst_slack_ns"] == pytest.approx(2.93)
    assert d["worst_path"] == "wb_adr_i[6] -> wb_dat_o[2]"


def test_parse_direction_violated_on_marker_despite_zero():
    # THE F1 regression: marker says VIOLATED while the number reads 0.00.
    d = sp.parse_direction(_SETUP_MET + _HOLD_VIOLATED_ZERO, "min")
    assert d["met"] is False
    assert d["worst_slack_ns"] == pytest.approx(0.00)
    assert d["worst_path"] == "u_rx_filler/wb_free_reg -> u_rx_filler/rd_reg"


def test_parse_coverage_counts():
    cov = sp.parse_coverage(_SETUP_MET + _HOLD_MET + _CHECK_TIMING)
    assert cov == {
        "unconstrained_max_delay_endpoints": 1461,
        "register_pins_no_clock": 756,
    }


def test_parse_coverage_defaults_zero_when_absent():
    cov = sp.parse_coverage(_SETUP_MET + _HOLD_MET + _CHECK_TIMING_CLEAN)
    assert cov == {"unconstrained_max_delay_endpoints": 0, "register_pins_no_clock": 0}


# ── run() exit-code + verdict contract ─────────────────────────────────────────
def test_run_clean_pass(tmp_path):
    rep, out = _write(tmp_path, _SETUP_MET + _HOLD_MET + _CHECK_TIMING_CLEAN)
    assert sp.run(rep, out) == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "pass"
    assert data["violations"] == []
    assert data["timing"]["setup"]["met"] is True
    assert data["timing"]["hold"]["met"] is True


def test_run_marker_keyed_fail_on_displayed_zero(tmp_path):
    # F1: must FAIL despite hold slack displaying 0.00; actual ~ 0.00 here.
    rep, out = _write(tmp_path, _SETUP_MET + _HOLD_VIOLATED_ZERO + _CHECK_TIMING)
    assert sp.run(rep, out) == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "fail"
    assert data["timing"]["hold"]["met"] is False
    v = [x for x in data["violations"] if x["dim"] == "timing_hold"]
    assert len(v) == 1
    assert v[0]["target"] == 0
    assert v[0]["path_id"] == "u_rx_filler/wb_free_reg -> u_rx_filler/rd_reg"


def test_run_negative_number_recorded_with_sig_digits4(tmp_path):
    # significant_digits=4: the recorded worst_slack_ns is the real negative value.
    rep, out = _write(tmp_path, _SETUP_MET + _HOLD_VIOLATED_NEG + _CHECK_TIMING)
    assert sp.run(rep, out) == 0
    data = json.loads(out.read_text())
    assert data["timing"]["hold"]["worst_slack_ns"] < 0
    v = [x for x in data["violations"] if x["dim"] == "timing_hold"][0]
    assert v["actual"] < 0


def test_run_coverage_recorded_not_gated(tmp_path):
    # 756 no-clock pins are recorded but do NOT change a passing verdict.
    rep, out = _write(tmp_path, _SETUP_MET + _HOLD_MET + _CHECK_TIMING)
    assert sp.run(rep, out) == 0
    data = json.loads(out.read_text())
    assert data["verdict"] == "pass"
    assert data["timing"]["coverage"]["register_pins_no_clock"] == 756


def test_run_missing_report_exit1(tmp_path):
    out = tmp_path / "timing-actual.json"
    assert sp.run(tmp_path / "nope.txt", out) == 1
    assert not out.exists()


def test_run_no_slack_line_exit3(tmp_path):
    # A -delay max section present but with no slack line -> unparseable, never pass.
    broken = re.sub(r"slack \(MET\)\s+2\.93", "", _SETUP_MET)
    rep, out = _write(tmp_path, broken + _HOLD_MET + _CHECK_TIMING_CLEAN)
    assert sp.run(rep, out) == 3
    assert not out.exists()


def test_run_marker_vs_sign_contradiction_exit3(tmp_path):
    # MET marker carrying a clearly-negative slack is a parse surprise -> exit 3.
    contradiction = re.sub(
        r"slack \(MET\)\s+2\.93",
        "slack (MET)                                        -0.5000",
        _SETUP_MET,
    )
    rep, out = _write(tmp_path, contradiction + _HOLD_MET + _CHECK_TIMING_CLEAN)
    assert sp.run(rep, out) == 3
    assert not out.exists()


def test_run_violated_marker_with_positive_slack_exit3(tmp_path):
    # Symmetric to the MET-with-negative case: a VIOLATED marker carrying a clearly
    # positive slack is a parse surprise -> exit 3 (both directions must be reported).
    contradiction = re.sub(
        r"slack \(MET\)\s+0\.20",
        "slack (VIOLATED)                                     2.5000",
        _HOLD_MET,
    )
    rep, out = _write(tmp_path, _SETUP_MET + contradiction + _CHECK_TIMING_CLEAN)
    assert sp.run(rep, out) == 3
    assert not out.exists()


def test_main_rejects_bad_arg_exit2():
    assert sp.main(["timing_rpt_parser.py"]) == 2


# ── Task 1: build_result + finalize subcommand ───────────────────────────────


def _workdir(tmp_path, report=None):
    report = (
        (_SETUP_MET + _HOLD_MET + _CHECK_TIMING_CLEAN) if report is None else report
    )
    (tmp_path / "timing-report.txt").write_text(report)
    return tmp_path


def test_build_result_pass_lean_shape(tmp_path):
    wd = _workdir(tmp_path)
    assert sp.build_result(wd, module="tpu_top", top="tpu_top") == 0
    env = json.loads((wd / "result.json").read_text())
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "timing-analysis",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["timing"]["setup"]["met"] is True and ss["timing"]["hold"]["met"] is True
    assert ss["violations"] == []
    assert "notes" not in ss  # lean shape: dropped field absent


def test_build_result_tooling_fail_on_unparseable(tmp_path):
    # A -delay max section with no slack line -> parser run() returns 3 (mirrors
    # test_run_no_slack_line_exit3 above).
    broken = re.sub(r"slack \(MET\)\s+2\.93", "", _SETUP_MET)
    wd = _workdir(tmp_path, report=broken + _HOLD_MET + _CHECK_TIMING_CLEAN)
    assert sp.build_result(wd, module="tpu_top", top="tpu_top") == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert (
        ss["failure_kind"] == "tooling"
        and ss["fail_reason"] == "timing-report.txt unparseable"
    )
    assert "timing" not in ss  # heavy pass-shape dropped on tooling-fail


def test_build_result_tooling_fail_on_missing_report(tmp_path):
    assert (
        sp.build_result(tmp_path, module="tpu_top", top="tpu_top") == 0
    )  # no report file
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert (
        ss["failure_kind"] == "tooling"
        and ss["fail_reason"] == "timing-report.txt missing"
    )


def test_finalize_cli_does_not_break_legacy_parse_cli(tmp_path):
    # the legacy bare-flag invocation still parses (no subcommand) — back-compat guard
    rep, out = _write(tmp_path, _SETUP_MET + _HOLD_MET + _CHECK_TIMING_CLEAN)
    assert (
        sp.main(["timing_rpt_parser.py", "--report", str(rep), "--out", str(out)]) == 0
    )
    assert json.loads(out.read_text())["verdict"] == "pass"


# ── Task 2: reproducibility-header derivations ───────────────────────────────


def test_parse_tool_from_primetime_version():
    assert sp.parse_tool("Version: M-2016.12-SP1\n") == "PrimeTime M-2016.12-SP1"
    assert sp.parse_tool("no version here") == "PrimeTime unknown"


def test_read_lib_db_from_config_tcl(tmp_path):
    (tmp_path / "config.tcl").write_text(
        "set TOP    tpu_top\nset LIB_DB /home/eda/Foundry/TSMC.90/slow.db\n"
    )
    assert sp.read_lib_db(tmp_path) == "/home/eda/Foundry/TSMC.90/slow.db"
    assert sp.read_lib_db(tmp_path / "nope") is None


def test_parse_clock_port_first_sdc(tmp_path):
    # The STA reads the SYNTHESIS SDC; lay out the workdir as runs/<N>/ under the module tree.
    wd = tmp_path / "asic" / "tpu_top" / "Design" / "timing-analysis" / "runs" / "3"
    wd.mkdir(parents=True)
    sdc = tmp_path / "asic" / "tpu_top" / "Design" / "synthesis" / "out"
    sdc.mkdir(parents=True)
    (sdc / "tpu_top_syn.sdc").write_text(
        "create_clock [get_ports i_clk]  -period 10  -waveform {0 5}\n"
    )
    assert sp.parse_clock(wd, top="tpu_top") == {"name": "i_clk", "period_ns": 10.0}
    assert sp.parse_clock(wd / "nope", top="tpu_top") is None


# ── Task 3: artifacts[] enumeration ──────────────────────────────────────────


def test_enumerate_artifacts_present_only_no_self(tmp_path):
    for rel in ["run_sta.tcl", "config.tcl", "timing-report.txt", "timing-actual.json"]:
        (tmp_path / rel).write_text("x")
    (tmp_path / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in sp.enumerate_artifacts(tmp_path)]
    assert paths == [
        "run_sta.tcl",
        "config.tcl",
        "timing-report.txt",
        "timing-actual.json",
    ]
    assert "result.json" not in paths
    assert all((tmp_path / p).is_file() for p in paths)  # only present files


# ── Task 4: golden test against the real tpu_top run ─────────────────────────


def test_golden_lean_against_real_tpu_top(tmp_path):
    import shutil

    ROOT = Path(__file__).resolve().parent / "fixtures" / "timing-tpu_top"
    # Fixture is rooted at Design/ (no `asic` path component — it would be .gitignored).
    # Copy under a module-root wrapper so parse_clock's parents[3] resolves the synthesis SDC.
    shutil.copytree(ROOT / "Design", tmp_path / "module" / "Design")
    wd = tmp_path / "module" / "Design" / "timing-analysis" / "runs" / "3"
    assert sp.build_result(wd, module="tpu_top", top="tpu_top") == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    # contract fields — exact to the real run
    assert env["status"] == "pass"
    assert ss["timing"]["setup"]["worst_slack_ns"] == pytest.approx(0.7252)
    assert ss["timing"]["setup"]["met"] is True
    assert (
        ss["timing"]["setup"]["worst_path"]
        == "systolic_reg/delay21_reg_0_ -> mac_10/o_result_reg_31_"
    )
    assert ss["timing"]["hold"]["worst_slack_ns"] == pytest.approx(0.2341)
    assert ss["timing"]["hold"]["met"] is True
    assert ss["timing"]["coverage"] == {
        "unconstrained_max_delay_endpoints": 1142,
        "register_pins_no_clock": 0,
    }
    assert ss["violations"] == []
    # reproducibility header — grounded in the real sources
    assert ss["tool"] == "PrimeTime M-2016.12-SP1"
    assert ss["lib_db"] == "/home/eda/Foundry/TSMC.90/slow.db"
    assert ss["clock"] == {"name": "i_clk", "period_ns": 10.0}
    assert ss["top_module"] == "tpu_top"
    # lean: dropped field ABSENT
    assert "notes" not in ss
    # artifacts present + no self-listing; produced_at normalized
    paths = [a["path"] for a in env["artifacts"]]
    assert paths == [
        "run_sta.tcl",
        "config.tcl",
        "timing-report.txt",
        "timing-actual.json",
    ]
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")


def test_golden_is_schema_valid(tmp_path):
    import shutil

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    ROOT = Path(__file__).resolve().parent / "fixtures" / "timing-tpu_top"
    shutil.copytree(ROOT / "Design", tmp_path / "module" / "Design")
    wd = tmp_path / "module" / "Design" / "timing-analysis" / "runs" / "3"
    sp.build_result(wd, module="tpu_top", top="tpu_top")
    env = json.loads((wd / "result.json").read_text())
    env_schema = json.loads(
        (REPO_ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (REPO_ROOT / "skills/timing-analysis/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        "https://veripower.local/schemas/envelope.schema.json",
        Resource.from_contents(env_schema),
    )
    Draft202012Validator(stage_schema, registry=registry).validate(
        env
    )  # raises on invalid
