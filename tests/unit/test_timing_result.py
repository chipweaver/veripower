"""Tests for skills/timing-analysis/scripts/timing/result.py (marker-keyed).

Fixtures preserve PrimeTime (M-2016.12-SP1) report syntax: bare `report_timing -delay max|min` prints the worst path per group, each
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


@pytest.mark.parametrize("seconds", [1e-9, 1e-12, 1e-10])
def test_native_units_preserve_slack_and_judgment(seconds):
    raw = 0.5e-9 / seconds
    text = f"Time_unit : {seconds} Second\n"
    for kind in ("max", "min"):
        text += f"-delay_type {kind}\nStartpoint: d\nEndpoint: q\nslack (MET) {raw}\n"
    timing = {
        "setup": sp.parse_direction(text, "max"),
        "hold": sp.parse_direction(text, "min"),
    }
    from timing import requirements

    verdict = requirements.compare(
        [
            {
                "id": "MARGIN",
                "target": {"dim": "timing_slack_ns", "op": ">=", "value": 1},
            }
        ],
        timing,
    )[0]
    assert verdict["actual"] == pytest.approx(0.5)
    assert verdict["met"] is False


@pytest.mark.parametrize("unit", ["", "Time_unit : N/A\n", "Time_unit : 0 Second\n"])
def test_timing_without_a_usable_unit_is_not_assumed_ns(unit):
    with pytest.raises(sp.ParseError, match="time unit"):
        sp.parse_direction(
            unit + "-delay_type max\nStartpoint: d\nslack (MET) 1.0\n", "max"
        )


# ── fixtures (faithful real-format excerpts) ─────────────────────────────────
SETUP_MET = """\
Time_unit : 1e-09 Second
****************************************
Report : timing
\t-path_type full
\t-delay_type max
\t-max_paths 1
\t-sort_by slack
Version: M-2016.12-SP1
****************************************


  Startpoint: input_data[6]
               (input port clocked by clock_a)
  Endpoint: output_data[2]
               (output port clocked by clock_a)
  Path Group: clock_a
  Path Type: max

  data arrival time                                   3.87
  data required time                                  6.80
  ---------------------------------------------------------------
  slack (MET)                                         2.93

"""

HOLD_MET = """\
****************************************
Report : timing
\t-delay_type min
\t-max_paths 1
\t-sort_by slack
Version: M-2016.12-SP1
****************************************


  Startpoint: storage/data_reg
               (rising edge-triggered flip-flop clocked by clock_a)
  Endpoint: storage/data_reg
               (rising edge-triggered flip-flop clocked by clock_a)
  Path Group: clock_a
  Path Type: min

  slack (MET)                                         0.20

"""

# Real case: displayed slack is 0.00 but the path is VIOLATED.
HOLD_VIOLATED_ZERO = """\
****************************************
Report : timing
\t-delay_type min
\t-max_paths 1
\t-sort_by slack
Version: M-2016.12-SP1
****************************************


  Startpoint: producer/ready_reg
               (rising edge-triggered flip-flop clocked by clock_a)
  Endpoint: consumer/read_reg
               (rising edge-triggered flip-flop clocked by clock_a)
  Path Group: clock_a
  Path Type: min

  slack (VIOLATED: increase significant digits)       0.00

"""

# significant_digits=4 case: the same path prints a real negative number.
# (re.sub, not .replace, so a whitespace mismatch fails loudly instead of no-op'ing.)
HOLD_VIOLATED_NEG = re.sub(
    r"slack \(VIOLATED[^)]*\)\s+0\.00",
    "slack (VIOLATED)                                    -0.0050",
    HOLD_VIOLATED_ZERO,
)

# check_timing output is in the report for the reader; the gate does not read it.
# Counts describe reported checks; they do not establish the timing scope of a design.
CHECK_TIMING = """\
Information: Checking 'unconstrained_endpoints'.
Warning: There are 1461 endpoints which are not constrained for maximum delay.

Information: Checking 'no_clock'.
Warning: There are 756 register clock pins with no clock.

check_timing succeeded.
"""


def coverage(out_setup: int | None) -> str:
    """Native report_analysis_coverage table; totals count checks, not distinct pins."""
    row = (
        ""
        if out_setup is None
        else f"out_setup           {out_setup:11d}{out_setup:10d} (100%)         0 (  0%)         0 (  0%)\n"
    )
    return (
        "Type of Check         Total              Met         Violated         Untested\n"
        "----------------------------------------------------------------------------\n"
        "setup                   584       584 (100%)         0 (  0%)         0 (  0%)\n"
        f"{row}"
        "----------------------------------------------------------------------------\n"
    )


COV_FULL = coverage(8)
COV_SHORT = coverage(2)


def write_timing_report(tmp_path, text):
    rep = tmp_path / "timing-report.txt"
    rep.write_text(text)
    return rep


# ── parse-unit tests ─────────────────────────────────────────────────────────
def test_parse_direction_met():
    d = sp.parse_direction(SETUP_MET + HOLD_MET, "max")
    assert d["met"] is True
    assert d["worst_slack_ns"] == pytest.approx(2.93)
    assert d["worst_path"] == "input_data[6] -> output_data[2]"


def test_parse_direction_violated_on_marker_despite_zero():
    # The regression: marker says VIOLATED while the number reads 0.00.
    d = sp.parse_direction(SETUP_MET + HOLD_VIOLATED_ZERO, "min")
    assert d["met"] is False
    assert d["worst_slack_ns"] == pytest.approx(0.00)
    assert d["worst_path"] == "producer/ready_reg -> consumer/read_reg"


# ── run() exit-code + verdict contract ─────────────────────────────────────────
def test_run_clean_pass(tmp_path):
    rep = write_timing_report(tmp_path, SETUP_MET + HOLD_MET + CHECK_TIMING + COV_FULL)
    rc, data = sp.run(rep)
    assert rc == 0
    assert data["verdict"] == "pass"
    assert data["timing"]["setup"]["met"] is True
    assert data["timing"]["hold"]["met"] is True


def test_run_marker_keyed_fail_on_displayed_zero(tmp_path):
    # Must FAIL despite hold slack displaying 0.00; actual ~ 0.00 here.
    rep = write_timing_report(
        tmp_path, SETUP_MET + HOLD_VIOLATED_ZERO + CHECK_TIMING + COV_FULL
    )
    rc, data = sp.run(rep)
    assert rc == 0
    assert data["verdict"] == "fail"
    assert data["timing"]["hold"]["met"] is False
    assert (
        data["timing"]["hold"]["worst_path"]
        == "producer/ready_reg -> consumer/read_reg"
    )


def test_run_negative_number_recorded_with_sig_digits4(tmp_path):
    # significant_digits=4: the recorded worst_slack_ns is the real negative value.
    rep = write_timing_report(
        tmp_path, SETUP_MET + HOLD_VIOLATED_NEG + CHECK_TIMING + COV_FULL
    )
    rc, data = sp.run(rep)
    assert rc == 0
    assert data["timing"]["hold"]["worst_slack_ns"] < 0
    assert data["timing"]["hold"]["met"] is False


def test_counts_do_not_create_a_completeness_measurement(tmp_path):
    wd = workdir(tmp_path, report=SETUP_MET + HOLD_MET + CHECK_TIMING + COV_SHORT)
    assert sp.finalize(wd, [], []) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"
    assert set(env["stage_specific"]["timing"]) == {"setup", "hold"}


def test_scope_judgment_can_reject_met_paths(tmp_path):
    wd = workdir(tmp_path, report=SETUP_MET + HOLD_MET + CHECK_TIMING + COV_FULL)
    rows = [
        {
            "id": "IO",
            "judge": "timing-analysis",
            "verbatim": "Required interface paths must be constrained",
        }
    ]
    judgments = [
        {
            "id": "IO",
            "met": False,
            "measured": "port report: q[1] has no required output delay",
        }
    ]
    assert sp.finalize(wd, rows, judgments, fix_owner="synthesis") == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail" and "IO" in env["stage_specific"]["fail_reason"]
    assert env["stage_specific"]["timing"]["setup"]["met"] is True
    assert env["stage_specific"]["fix_owner"] == "synthesis"


def test_unconstrained_endpoints_alone_never_fail_a_run(tmp_path):
    # Global warning counts are evidence for the stage owner, not an automatic
    # scope verdict. The reported timing measurements are still available.
    wd = workdir(tmp_path, report=SETUP_MET + HOLD_MET + CHECK_TIMING + COV_FULL)
    (wd / "config.tcl").write_text("# current test setup\n")
    assert sp.finalize(wd, [], []) == 0
    assert json.loads((wd / "result.json").read_text())["status"] == "pass"


def test_report_counts_do_not_override_a_timing_violation(tmp_path):
    # Report counts do not change the measured hold violation.
    wd = workdir(
        tmp_path, report=SETUP_MET + HOLD_VIOLATED_NEG + CHECK_TIMING + COV_SHORT
    )
    (wd / "config.tcl").write_text("# current test setup\n")
    assert sp.finalize(wd, [], []) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["timing"]["hold"]["met"] is False


def test_run_missing_report_exit1(tmp_path):
    rc, payload = sp.run(tmp_path / "nope.txt")
    assert rc == 1 and payload is None


def test_run_no_slack_line_exit3(tmp_path):
    # A -delay max section present but with no slack line -> unparseable, never pass.
    broken = re.sub(r"slack \(MET\)\s+2\.93", "", SETUP_MET)
    rep = write_timing_report(tmp_path, broken + HOLD_MET + CHECK_TIMING + COV_FULL)
    rc, payload = sp.run(rep)
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_marker_vs_sign_contradiction_exit3(tmp_path):
    # MET marker carrying a clearly-negative slack is a parse surprise -> exit 3.
    contradiction = re.sub(
        r"slack \(MET\)\s+2\.93",
        "slack (MET)                                        -0.5000",
        SETUP_MET,
    )
    rep = write_timing_report(
        tmp_path, contradiction + HOLD_MET + CHECK_TIMING + COV_FULL
    )
    rc, payload = sp.run(rep)
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_violated_marker_with_positive_slack_exit3(tmp_path):
    # Symmetric to the MET-with-negative case: a VIOLATED marker carrying a clearly
    # positive slack is a parse surprise -> exit 3 (both directions must be reported).
    contradiction = re.sub(
        r"slack \(MET\)\s+0\.20",
        "slack (VIOLATED)                                     2.5000",
        HOLD_MET,
    )
    rep = write_timing_report(
        tmp_path, SETUP_MET + contradiction + CHECK_TIMING + COV_FULL
    )
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


# ── finalize + finalize subcommand ───────────────────────────────────────


def workdir(tmp_path, report=None, rows=()):
    report = (
        (SETUP_MET + HOLD_MET + CHECK_TIMING + COV_FULL) if report is None else report
    )
    (tmp_path / "timing-report.txt").write_text(report)
    sd = tmp_path / "spec"
    sd.mkdir(exist_ok=True)
    (sd / "requirements.json").write_text(json.dumps(list(rows)))
    (tmp_path / "dispatch.json").write_text(
        json.dumps({"inputs": {"requirements": str(sd)}})
    )
    return tmp_path


def test_finalize_pass_lean_shape(tmp_path):
    wd = workdir(tmp_path)
    (wd / "config.tcl").write_text("# current test setup\n")
    assert sp.finalize(wd, [], []) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "timing-analysis"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["timing"]["setup"]["met"] is True and ss["timing"]["hold"]["met"] is True
    assert ss["requirements"] == []
    assert "notes" not in ss  # lean shape: dropped field absent


def test_finalize_tooling_fail_on_unparseable(tmp_path):
    # A -delay max section with no slack line -> parser run() returns 3 (mirrors
    # test_run_no_slack_line_exit3 above).
    broken = re.sub(r"slack \(MET\)\s+2\.93", "", SETUP_MET)
    wd = workdir(tmp_path, report=broken + HOLD_MET + CHECK_TIMING + COV_FULL)
    (wd / "config.tcl").write_text("# current test setup\n")
    assert sp.finalize(wd, [], []) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "timing-report.txt unparseable"
    assert "timing" not in ss  # heavy pass-shape dropped when nothing was graded


def test_finalize_tooling_fail_on_missing_report(tmp_path):
    assert sp.finalize(tmp_path, [], []) == 0  # no report file
    ss = json.loads((tmp_path / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "timing-report.txt missing"


def test_fail_reason_wins_over_a_clean_gate(tmp_path):
    # The caller watched pt_shell; this verb only sees what landed on disk. A report
    # that parses clean does not outrank a declared failure.
    wd = workdir(tmp_path)
    assert (
        sp.finalize(
            wd,
            [],
            [],
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
    assert "timing" not in ss


def test_finalize_blocked_on_empty_fail_reason(tmp_path):
    wd = workdir(tmp_path)
    assert sp.finalize(wd, [], [], fail_reason="  ") == 2
    assert not (wd / "result.json").exists()


def test_finalize_cli_declared_failure(tmp_path):
    # A run PrimeTime never reached leaves nothing on disk to grade, so the cause is
    # reachable only through this flag — never through a hand-written envelope.
    wd = workdir(tmp_path)
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
    # End-to-end through the finalize CLI (handler import + arg mapping), not just
    # in-process finalize.
    wd = workdir(tmp_path)
    MAIN = REPO_ROOT / "skills/timing-analysis/scripts/timing/__main__.py"
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"]) == ("timing-analysis", "pass")


ROWS = [
    {
        "id": "R-1",
        "verbatim": "综合与 STA 后无 setup/hold 违例",
        "judge": "timing-analysis",
    },
    {"id": "R-2", "verbatim": "area", "judge": "synthesis"},
]


def cli(wd, *extra):
    MAIN = REPO_ROOT / "skills/timing-analysis/scripts/timing/__main__.py"
    return subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd), *extra],
        capture_output=True,
        text=True,
    )


def test_the_agents_verdict_on_its_rows_lands_in_the_envelope(tmp_path):
    wd = workdir(tmp_path, rows=ROWS)
    declared = [
        {
            "id": "R-1",
            "met": True,
            "actual": "setup +2.93 ns, hold +0.20 ns",
            "measured": "read from the run's own report",
        }
    ]
    r = cli(wd, "--requirements", json.dumps(declared))
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass" and env["stage_specific"]["requirements"] == declared


def test_a_declared_miss_fails_a_run_primetime_passed(tmp_path):
    wd = workdir(tmp_path, rows=ROWS)
    r = cli(
        wd,
        "--requirements",
        json.dumps(
            [{"id": "R-1", "met": False, "measured": "read from the run's own report"}]
        ),
        "--fix-owner",
        "synthesis",
    )
    assert r.returncode == 0, r.stderr
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert (
        ss["fail_reason"] == "requirement(s) not met: R-1"
        and ss["fix_owner"] == "synthesis"
    )


def test_a_row_nobody_judged_is_blocked(tmp_path):
    wd = workdir(tmp_path, rows=ROWS)
    r = cli(wd)
    assert r.returncode == 2 and "R-1" in r.stderr
    assert not (wd / "result.json").exists()


def target(value=0, op=">=", dim="timing_slack_ns"):
    return {
        "id": "T",
        "judge": "timing-analysis",
        "verbatim": "timing bound",
        "target": {"dim": dim, "op": op, "value": value},
    }


@pytest.mark.parametrize(
    "value,op,expected",
    [
        (0, ">=", True),
        (0.2, ">=", True),
        (0.2, ">", False),
        (0.3, ">=", False),
        (0.2, "<=", True),
        (0.2, "<", False),
    ],
)
def test_numeric_targets_are_computed_from_worst_setup_and_hold(
    tmp_path, value, op, expected
):
    wd = workdir(tmp_path, rows=[target(value, op)])
    r = cli(wd)
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    row = env["stage_specific"]["requirements"][0]
    assert row["actual"] == 0.2
    assert row["met"] is expected
    assert env["status"] == ("pass" if expected else "fail")


def test_numeric_target_cannot_pass_a_rounded_zero_violation(tmp_path):
    wd = workdir(
        tmp_path,
        rows=[target()],
        report=SETUP_MET + HOLD_VIOLATED_ZERO + CHECK_TIMING + COV_FULL,
    )
    assert cli(wd).returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["requirements"][0]["met"] is False


def test_declared_verdict_cannot_replace_numeric_comparison(tmp_path):
    wd = workdir(tmp_path, rows=[target(5)])
    r = cli(
        wd,
        "--requirements",
        json.dumps([{"id": "T", "met": True, "actual": 99, "measured": "claimed"}]),
    )
    assert r.returncode == 2 and "overridden" in r.stderr
    assert not (wd / "result.json").exists()


@pytest.mark.parametrize(
    "row",
    [target(dim="unknown"), target(op="=="), target(True), target(float("nan"))],
)
def test_unknown_or_invalid_timing_target_is_named(tmp_path, row):
    wd = workdir(tmp_path, rows=[row])
    r = cli(wd)
    assert r.returncode == 2 and "unsupported timing target" in r.stderr
    assert not (wd / "result.json").exists()


def test_numeric_and_agent_judged_rows_can_coexist(tmp_path):
    wd = workdir(tmp_path, rows=[target(), ROWS[0]])
    declared = [{"id": "R-1", "met": True, "measured": "report scope inspected"}]
    r = cli(wd, "--requirements", json.dumps(declared))
    assert r.returncode == 0, r.stderr
    rows = json.loads((wd / "result.json").read_text())["stage_specific"][
        "requirements"
    ]
    assert [r["id"] for r in rows] == ["T", "R-1"]
    assert rows[1] == declared[0]


# ── artifacts[] enumeration ──────────────────────────────────────────────────


def test_enumerate_artifacts_present_only_no_self(tmp_path):
    for rel in ["run_sta.tcl", "config.tcl", "timing-report.txt"]:
        (tmp_path / rel).write_text("x")
    (tmp_path / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in sp.enumerate_artifacts(tmp_path)]
    assert set(paths) == {"run_sta.tcl", "config.tcl", "timing-report.txt"}
    assert "result.json" not in paths
    assert all((tmp_path / p).is_file() for p in paths)  # only present files


# Result-schema checks.


def test_report_values_and_paths_reach_result(tmp_path):
    import shutil

    ROOT = Path(__file__).resolve().parent / "fixtures" / "timing-reports"
    wd = tmp_path / "timing"
    shutil.copytree(ROOT, wd)
    (wd / "run_sta.tcl").write_text("# tool entrypoint\n")
    (wd / "config.tcl").write_text("# current test setup\n")
    assert sp.finalize(wd, [], []) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    # Replay the recorded setup/hold measurements without inventing a scope metric.
    assert env["status"] == "pass"
    assert set(ss["timing"]) == {"setup", "hold"}
    # Report values are copied with their units and endpoint names.
    assert ss["timing"]["setup"]["worst_slack_ns"] == pytest.approx(0.7252)
    assert ss["timing"]["setup"]["met"] is True
    assert (
        ss["timing"]["setup"]["worst_path"] == "launch_register/Q -> capture_register/D"
    )
    assert ss["timing"]["hold"]["worst_slack_ns"] == pytest.approx(0.2341)
    assert ss["timing"]["hold"]["met"] is True
    assert ss["tool"] == "PrimeTime M-2016.12-SP1"
    # every copied header field is gone: the lib_db is in the promoted config.tcl and
    # in the kernel's own reap-time environment record, the clock is in the
    # fingerprint-pinned synthesis SDC, and the top name was never anything but typed.
    for dropped in ("lib_db", "clock", "top_module"):
        assert dropped not in ss
    # artifacts present + no self-listing; produced_at normalized
    paths = [a["path"] for a in env["artifacts"]]
    assert set(paths) == {"run_sta.tcl", "config.tcl", "timing-report.txt"}
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")


def test_pass_result_is_schema_valid(tmp_path):
    import shutil

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    ROOT = Path(__file__).resolve().parent / "fixtures" / "timing-reports"
    wd = tmp_path / "timing"
    shutil.copytree(ROOT, wd)
    (wd / "run_sta.tcl").write_text("# tool entrypoint\n")
    (wd / "config.tcl").write_text("# test setup\n")
    sp.finalize(wd, [], [])
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


@pytest.mark.parametrize("direction", ["setup", "hold"])
def test_numeric_rows_do_not_inherit_overall_sta_failure(tmp_path, direction):
    comparisons = [
        (">=", -2, True),
        (">", -2, True),
        ("<=", 0, True),
        ("<", 0, True),
        (">=", -1, True),
        (">", -1, False),
        ("<=", -2, False),
        ("<", -1, False),
    ]
    rows = [
        dict(target(value, op), id=str(i))
        for i, (op, value, unused) in enumerate(comparisons)
    ]
    setup, hold = SETUP_MET, HOLD_MET
    if direction == "setup":
        setup = setup.replace("slack (MET)", "slack (VIOLATED)").replace(
            "2.93", "-1.00"
        )
    else:
        hold = hold.replace("slack (MET)", "slack (VIOLATED)").replace("0.20", "-1.00")
    wd = workdir(tmp_path, rows=rows, report=setup + hold + CHECK_TIMING + COV_FULL)
    assert cli(wd).returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    assert env["stage_specific"]["fail_reason"] == "setup/hold timing not met"
    verdicts = env["stage_specific"]["requirements"]
    assert [r["actual"] for r in verdicts] == [-1.0] * len(rows)
    assert [r["met"] for r in verdicts] == [v for unused, unused, v in comparisons]


@pytest.mark.parametrize("display", ["0.00", "-0.00"])
def test_rounded_violation_respects_the_comparison_direction(tmp_path, display):
    comparisons = [
        (">=", 0, False),
        (">", 0, False),
        ("<=", 0, True),
        ("<", 0, True),
        (">=", -1, True),
        ("<=", -1, False),
    ]
    rows = [
        dict(target(value, op), id=str(i))
        for i, (op, value, unused) in enumerate(comparisons)
    ]
    hold = HOLD_VIOLATED_ZERO.replace("0.00", display)
    wd = workdir(tmp_path, rows=rows, report=SETUP_MET + hold + CHECK_TIMING + COV_FULL)
    assert cli(wd).returncode == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "fail"
    verdicts = env["stage_specific"]["requirements"]
    assert all(r["actual"] == 0 for r in verdicts)
    assert [r["met"] for r in verdicts] == [v for unused, unused, v in comparisons]


def test_missing_native_coverage_report_is_incomplete(tmp_path):
    report = write_timing_report(tmp_path, SETUP_MET + HOLD_MET + CHECK_TIMING)
    assert sp.run(report) == (3, None)


def test_native_coverage_needs_no_custom_boundary_counter(tmp_path):
    text = SETUP_MET + HOLD_MET + CHECK_TIMING + COV_FULL
    rc, data = sp.run(write_timing_report(tmp_path, text))
    assert rc == 0 and set(data["timing"]) == {"setup", "hold"}
