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
    # positive slack is a parse surprise -> exit 3 (spec §7 requires both directions).
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
