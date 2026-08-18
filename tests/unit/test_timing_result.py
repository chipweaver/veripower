"""Tests for skills/timing-analysis/scripts/timing/result.py (marker-keyed).

Fixtures are real-format excerpts from the pt2016 (M-2016.12-SP1) sdc_controller
corpus: bare `report_timing -delay max|min` prints the worst path per group, each
block ending in a 'slack (MET)' / 'slack (VIOLATED...)' line; the displayed slack
rounds to report precision, so the MARKER — not the number — decides met/violated.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "timing-analysis" / "scripts"))

from timing import result as sp  # noqa: E402

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

# Real case: displayed slack is 0.00 but the path is VIOLATED.
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

# check_timing output is in the report for the reader; the gate does not read it.
# 1461 unconstrained endpoints on a healthy design is ordinary — reset ports carry no
# input delay, so every async-reset flop lands in that count.
_CHECK_TIMING = """\
Information: Checking 'unconstrained_endpoints'.
Warning: There are 1461 endpoints which are not constrained for maximum delay.

Information: Checking 'no_clock'.
Warning: There are 756 register clock pins with no clock.

check_timing succeeded.
"""


def _coverage(output_bits: int, out_setup: int | None) -> str:
    """A report_analysis_coverage table plus the boundary line run_sta.tcl emits.
    `out_setup=None` drops the row entirely, which is what PrimeTime does for a run
    that timed no output at all."""
    row = (
        ""
        if out_setup is None
        else f"out_setup           {out_setup:11d}{out_setup:10d} (100%)         0 (  0%)         0 (  0%)\n"
    )
    return (
        f"Boundary output bits: {output_bits}\n"
        "Type of Check         Total              Met         Violated         Untested\n"
        "----------------------------------------------------------------------------\n"
        "setup                   584       584 (100%)         0 (  0%)         0 (  0%)\n"
        f"{row}"
        "----------------------------------------------------------------------------\n"
    )


_COV_FULL = _coverage(8, 8)  # every output bit timed
_COV_SHORT = _coverage(8, 2)  # the SDC reached two of them


def _write(tmp_path, text):
    rep = tmp_path / "timing-report.txt"
    rep.write_text(text)
    return rep


# ── parse-unit tests ─────────────────────────────────────────────────────────
def test_parse_direction_met():
    d = sp.parse_direction(_SETUP_MET + _HOLD_MET, "max")
    assert d["met"] is True
    assert d["worst_slack_ns"] == pytest.approx(2.93)
    assert d["worst_path"] == "wb_adr_i[6] -> wb_dat_o[2]"


def test_parse_direction_violated_on_marker_despite_zero():
    # The regression: marker says VIOLATED while the number reads 0.00.
    d = sp.parse_direction(_SETUP_MET + _HOLD_VIOLATED_ZERO, "min")
    assert d["met"] is False
    assert d["worst_slack_ns"] == pytest.approx(0.00)
    assert d["worst_path"] == "u_rx_filler/wb_free_reg -> u_rx_filler/rd_reg"


def test_parse_coverage_reads_the_boundary_pair():
    cov = sp.parse_coverage(_SETUP_MET + _HOLD_MET + _CHECK_TIMING + _COV_FULL)
    assert cov == {"output_bits": 8, "output_bits_timed": 8}


def test_an_absent_out_setup_row_means_no_output_was_timed():
    # PrimeTime drops the row entirely rather than printing a zero.
    cov = sp.parse_coverage(_SETUP_MET + _HOLD_MET + _coverage(8, None))
    assert cov == {"output_bits": 8, "output_bits_timed": 0}


def test_parse_coverage_raises_without_the_boundary_line():
    with pytest.raises(sp.ParseError):
        sp.parse_coverage(_SETUP_MET + _HOLD_MET + _CHECK_TIMING)


def test_parse_coverage_raises_without_the_coverage_table():
    # A truncated report would otherwise read as a design with no outputs, which is
    # the one wrong answer this gate cannot afford.
    with pytest.raises(sp.ParseError):
        sp.parse_coverage(_SETUP_MET + _HOLD_MET + "Boundary output bits: 8\n")


# ── run() exit-code + verdict contract ─────────────────────────────────────────
def test_run_clean_pass(tmp_path):
    rep = _write(tmp_path, _SETUP_MET + _HOLD_MET + _CHECK_TIMING + _COV_FULL)
    rc, data = sp.run(rep)
    assert rc == 0
    assert data["verdict"] == "pass"
    assert data["violations"] == []
    assert data["timing"]["setup"]["met"] is True
    assert data["timing"]["hold"]["met"] is True


def test_run_marker_keyed_fail_on_displayed_zero(tmp_path):
    # Must FAIL despite hold slack displaying 0.00; actual ~ 0.00 here.
    rep = _write(tmp_path, _SETUP_MET + _HOLD_VIOLATED_ZERO + _CHECK_TIMING + _COV_FULL)
    rc, data = sp.run(rep)
    assert rc == 0
    assert data["verdict"] == "fail"
    assert data["timing"]["hold"]["met"] is False
    v = [x for x in data["violations"] if x["dim"] == "timing_hold"]
    assert len(v) == 1
    assert v[0]["target"] == 0
    assert v[0]["path_id"] == "u_rx_filler/wb_free_reg -> u_rx_filler/rd_reg"


def test_run_negative_number_recorded_with_sig_digits4(tmp_path):
    # significant_digits=4: the recorded worst_slack_ns is the real negative value.
    rep = _write(tmp_path, _SETUP_MET + _HOLD_VIOLATED_NEG + _CHECK_TIMING + _COV_FULL)
    rc, data = sp.run(rep)
    assert rc == 0
    assert data["timing"]["hold"]["worst_slack_ns"] < 0
    v = [x for x in data["violations"] if x["dim"] == "timing_hold"][0]
    assert v["actual"] < 0


def test_uncovered_is_none_only_when_the_boundary_is_whole():
    assert sp.uncovered({"output_bits": 8, "output_bits_timed": 8}) is None
    assert sp.uncovered({"output_bits": 0, "output_bits_timed": 0}) is None
    assert "2 of 8 output bits" in sp.uncovered(
        {"output_bits": 8, "output_bits_timed": 2}
    )


def test_an_untimed_boundary_cannot_pass(tmp_path):
    # Both directions MET, and the SDC reached two of eight output bits. The markers
    # grade what PrimeTime analyzed, so they cannot answer for the rest.
    wd = _workdir(tmp_path, report=_SETUP_MET + _HOLD_MET + _CHECK_TIMING + _COV_SHORT)
    assert sp.build_result(wd, fix_owner="synthesis") == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert "2 of 8 output bits" in ss["fail_reason"]
    assert ss["fix_owner"] == "synthesis"
    assert ss["timing"]["setup"]["met"] is True  # the measurements still land
    assert ss["violations"] == []


def test_unconstrained_endpoints_alone_never_fail_a_run(tmp_path):
    # THE regression this metric replaced. 1461 unconstrained endpoints and 756
    # no-clock register pins are in this report, and the boundary is fully timed, so
    # it passes: those counts are ordinary on a healthy design, because reset ports
    # carry no input delay. Measured 0..4242 across eight synthesized designs with a
    # complete SDC, and identical to the broken SDC on two of them.
    wd = _workdir(tmp_path, report=_SETUP_MET + _HOLD_MET + _CHECK_TIMING + _COV_FULL)
    assert sp.build_result(wd) == 0
    assert json.loads((wd / "result.json").read_text())["status"] == "pass"


def test_an_untimed_boundary_outranks_a_missed_target(tmp_path):
    # Hold is violated AND the boundary is short. The shortfall wins: routing a ppa
    # fail would send someone to close a path on a boundary that was never timed.
    wd = _workdir(
        tmp_path, report=_SETUP_MET + _HOLD_VIOLATED_NEG + _CHECK_TIMING + _COV_SHORT
    )
    assert sp.build_result(wd) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["violations"][0]["dim"] == "timing_hold"


def test_run_missing_report_exit1(tmp_path):
    rc, payload = sp.run(tmp_path / "nope.txt")
    assert rc == 1 and payload is None


def test_run_no_slack_line_exit3(tmp_path):
    # A -delay max section present but with no slack line -> unparseable, never pass.
    broken = re.sub(r"slack \(MET\)\s+2\.93", "", _SETUP_MET)
    rep = _write(tmp_path, broken + _HOLD_MET + _CHECK_TIMING + _COV_FULL)
    rc, payload = sp.run(rep)
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_marker_vs_sign_contradiction_exit3(tmp_path):
    # MET marker carrying a clearly-negative slack is a parse surprise -> exit 3.
    contradiction = re.sub(
        r"slack \(MET\)\s+2\.93",
        "slack (MET)                                        -0.5000",
        _SETUP_MET,
    )
    rep = _write(tmp_path, contradiction + _HOLD_MET + _CHECK_TIMING + _COV_FULL)
    rc, payload = sp.run(rep)
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_violated_marker_with_positive_slack_exit3(tmp_path):
    # Symmetric to the MET-with-negative case: a VIOLATED marker carrying a clearly
    # positive slack is a parse surprise -> exit 3 (both directions must be reported).
    contradiction = re.sub(
        r"slack \(MET\)\s+0\.20",
        "slack (VIOLATED)                                     2.5000",
        _HOLD_MET,
    )
    rep = _write(tmp_path, _SETUP_MET + contradiction + _CHECK_TIMING + _COV_FULL)
    rc, payload = sp.run(rep)
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    MAIN = REPO_ROOT / "skills/timing-analysis/scripts/timing/__main__.py"
    # --workdir is the one flag finalize cannot infer; omitting it is argparse exit 2,
    # never a written envelope.
    r = subprocess.run(
        ["python3", str(MAIN), "finalize"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert not (tmp_path / "result.json").exists()


# ── build_result + finalize subcommand ───────────────────────────────────────


def _workdir(tmp_path, report=None):
    report = (
        (_SETUP_MET + _HOLD_MET + _CHECK_TIMING + _COV_FULL)
        if report is None
        else report
    )
    (tmp_path / "timing-report.txt").write_text(report)
    return tmp_path


def test_build_result_pass_lean_shape(tmp_path):
    wd = _workdir(tmp_path)
    assert sp.build_result(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "timing-analysis"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["timing"]["setup"]["met"] is True and ss["timing"]["hold"]["met"] is True
    assert ss["violations"] == []
    assert "notes" not in ss  # lean shape: dropped field absent


def test_build_result_tooling_fail_on_unparseable(tmp_path):
    # A -delay max section with no slack line -> parser run() returns 3 (mirrors
    # test_run_no_slack_line_exit3 above).
    broken = re.sub(r"slack \(MET\)\s+2\.93", "", _SETUP_MET)
    wd = _workdir(tmp_path, report=broken + _HOLD_MET + _CHECK_TIMING + _COV_FULL)
    assert sp.build_result(wd) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "timing-report.txt unparseable"
    assert "timing" not in ss  # heavy pass-shape dropped when nothing was graded


def test_build_result_tooling_fail_on_missing_report(tmp_path):
    assert sp.build_result(tmp_path) == 0  # no report file
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "timing-report.txt missing"


def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps build_result: any internal raise -> exit 2 (BLOCKED), never
    # status=fail. (The old main() finalize branch had this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(sp, "build_result", boom)
    assert sp.finalize(tmp_path) == 2


def test_fail_reason_wins_over_a_clean_gate(tmp_path):
    # The caller watched pt_shell; this verb only sees what landed on disk. A report
    # that parses clean does not outrank a declared failure.
    wd = _workdir(tmp_path)
    assert (
        sp.build_result(
            wd,
            fix_owner="synthesis",
            fail_reason="PT license unavailable",
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    ss = env["stage_specific"]
    assert (ss["fail_reason"], ss["fix_owner"]) == (
        "PT license unavailable",
        "synthesis",
    )
    # An early-fail carries no measurements: PT produced none this caller trusts.
    assert "timing" not in ss and "violations" not in ss


def test_finalize_blocked_on_empty_fail_reason(tmp_path):
    wd = _workdir(tmp_path)
    assert sp.finalize(wd, fail_reason="  ") == 2
    assert not (wd / "result.json").exists()


def test_finalize_cli_declared_failure(tmp_path):
    # A run PrimeTime never reached leaves nothing on disk to grade, so the cause is
    # reachable only through this flag — never through a hand-written envelope.
    wd = _workdir(tmp_path)
    MAIN = REPO_ROOT / "skills/timing-analysis/scripts/timing/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--fail-reason",
            "PT license unavailable",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "PT license unavailable"


def test_finalize_cli_happy_path(tmp_path):
    # End-to-end through _cmd_finalize (handler import + arg mapping), not just
    # in-process build_result.
    wd = _workdir(tmp_path)
    MAIN = REPO_ROOT / "skills/timing-analysis/scripts/timing/__main__.py"
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"]) == ("timing-analysis", "pass")


def test_parse_tool_from_primetime_version():
    assert sp.parse_tool("Version: M-2016.12-SP1\n") == "PrimeTime M-2016.12-SP1"
    assert sp.parse_tool("no version here") == "PrimeTime unknown"


# ── artifacts[] enumeration ──────────────────────────────────────────────────


def test_enumerate_artifacts_present_only_no_self(tmp_path):
    for rel in ["run_sta.tcl", "config.tcl", "timing-report.txt"]:
        (tmp_path / rel).write_text("x")
    (tmp_path / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in sp.enumerate_artifacts(tmp_path)]
    assert paths == [
        "run_sta.tcl",
        "config.tcl",
        "timing-report.txt",
    ]
    assert "result.json" not in paths
    assert all((tmp_path / p).is_file() for p in paths)  # only present files


# ── golden test against the real tpu_top run ─────────────────────────────────


def test_golden_lean_against_real_tpu_top(tmp_path):
    import shutil

    ROOT = Path(__file__).resolve().parent / "fixtures" / "timing-tpu_top"
    # Fixture is rooted at Design/ (no `asic` path component — it would be .gitignored).
    shutil.copytree(ROOT / "Design", tmp_path / "module" / "Design")
    wd = tmp_path / "module" / "Design" / "timing-analysis" / "runs" / "3"
    assert sp.build_result(wd) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    # A real tpu_top run: both directions MET, its whole boundary timed, and 1142
    # endpoints left unconstrained all the same. It passes, and that is the point —
    # those endpoints are the reset paths every design has.
    assert env["status"] == "pass"
    assert ss["timing"]["coverage"] == {"output_bits": 74, "output_bits_timed": 74}
    # contract fields — exact to the real run
    assert ss["timing"]["setup"]["worst_slack_ns"] == pytest.approx(0.7252)
    assert ss["timing"]["setup"]["met"] is True
    assert (
        ss["timing"]["setup"]["worst_path"]
        == "systolic_reg/delay21_reg_0_ -> mac_10/o_result_reg_31_"
    )
    assert ss["timing"]["hold"]["worst_slack_ns"] == pytest.approx(0.2341)
    assert ss["timing"]["hold"]["met"] is True
    assert ss["violations"] == []
    assert ss["tool"] == "PrimeTime M-2016.12-SP1"
    # every copied header field is gone: the lib_db is in the promoted config.tcl and
    # in the kernel's own reap-time environment record, the clock is in the
    # fingerprint-pinned synthesis SDC, and the top name was never anything but typed.
    for dropped in ("lib_db", "clock", "top_module"):
        assert dropped not in ss
    # artifacts present + no self-listing; produced_at normalized
    paths = [a["path"] for a in env["artifacts"]]
    assert paths == [
        "run_sta.tcl",
        "config.tcl",
        "timing-report.txt",
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
    sp.build_result(wd)
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
