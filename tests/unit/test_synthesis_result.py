"""Tests for skills/synthesis/scripts/synthesis/result.py (grounded format).

Fixtures excerpted from the real Synopsys DC L-2016.03-SP1 sdc_controller corpus:
area.rpt (one 'Total cell area:' summary; a separate 'Total area: undefined' line)
and qor.rpt (one 'Critical Path Slack:' per Timing Path Group block + a design
'WNS / Number of Violating Paths' summary).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills" / "synthesis" / "scripts"))

from synthesis import result as sp  # noqa: E402

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

# Observed on a real DC L-2016.03-SP1 run whose only paths were reg -> output port with no
# set_output_delay: the group is "(none)" and DC prints the slack as the literal `uninit`.
QOR_UNINIT = """\
  Timing Path Group (none)
  -----------------------------------
  Critical Path Length:          0.21
  Critical Path Slack:         uninit
  Critical Path Clk Period:       n/a
  -----------------------------------

  Design  WNS: 0.00  TNS: 0.00  Number of Violating Paths: 0
"""

# Same run shape with one constrained group added: only the group that HAS a slack counts.
QOR_UNINIT_PLUS_REAL = """\
  Timing Path Group (none)
  -----------------------------------
  Critical Path Slack:         uninit
  -----------------------------------

  Timing Path Group 'clk'
  -----------------------------------
  Critical Path Slack:           6.51
  -----------------------------------

  Design  WNS: 0.00  TNS: 0.00  Number of Violating Paths: 0
"""


AREA_SRC = "area.rpt Total cell area"
# The slack a synthesis run compares is setup only — the sentence says so, which is the point.
SLACK_SRC = (
    "qor.rpt worst Critical Path Slack across 2 group(s) (min) "
    "— setup only; hold is timing-analysis's"
)


def _stage(tmp_path, area=SAMPLE_AREA, qor=SAMPLE_QOR):
    """Write reports/{area,qor}.rpt under tmp_path; return (reports_dir, out_path)."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "area.rpt").write_text(area)
    (reports / "qor.rpt").write_text(qor)
    return reports


def _row(rid, dim, op, value, judge="synthesis"):
    return {
        "id": rid,
        "verbatim": f"{dim} {op} {value}",
        "judge": judge,
        "target": {"dim": dim, "op": op, "value": value},
    }


AREA_OK = _row("R-A", "area_um2", "<=", 80000.0)
SLACK_OK = _row("R-S", "timing_slack_ns", ">=", 0.5)
SLACK_TIGHT = _row("R-S", "timing_slack_ns", ">=", 2.0)
AREA_TINY = _row("R-A", "area_um2", "<=", 1.0)
NAND2 = {"id": "R-N", "verbatim": "逻辑 ≤ 0.45M NAND2 等效门", "judge": "synthesis"}


def _spec(tmp_path, rows):
    """A specification root holding the ledger, and the dispatch.json pointing at it."""
    sd = tmp_path / "spec"
    sd.mkdir(exist_ok=True)
    (sd / "requirements.json").write_text(json.dumps(rows))
    (tmp_path / "dispatch.json").write_text(
        json.dumps({"inputs": {"requirements": str(sd)}})
    )
    return sd


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


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
    # --workdir is the one flag finalize cannot infer; omitting it is argparse exit 2,
    # never a written envelope.
    r = subprocess.run(
        ["python3", str(MAIN), "finalize"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert not (tmp_path / "result.json").exists()


# ── run() exit-code contract ──────────────────────────────────────────────────
def test_run_slack_min_regression(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, [])
    assert rc == 0
    slack = [a for a in data["measurements"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(0.95)
    assert slack["value"] != pytest.approx(16.99)


def test_run_area_disambiguation(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, [])
    assert rc == 0
    area = [a for a in data["measurements"] if a["dim"] == "area_um2"][0]
    assert area["value"] == pytest.approx(65018.219263)


def test_run_judges_each_targeted_row(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, [AREA_OK, SLACK_OK])
    assert rc == 0
    assert data["requirements"] == [
        {
            "id": "R-A",
            "met": True,
            "actual": pytest.approx(65018.219263),
            "measured": AREA_SRC,
        },
        {
            "id": "R-S",
            "met": True,
            "actual": pytest.approx(0.95),
            "measured": SLACK_SRC,
        },
    ]


def test_run_a_missed_row_is_still_exit0(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, [SLACK_TIGHT])
    assert rc == 0  # a miss is a verdict, not a tooling failure
    assert data["requirements"] == [
        {
            "id": "R-S",
            "met": False,
            "actual": pytest.approx(0.95),
            "measured": SLACK_SRC,
        }
    ]


def test_run_uses_the_engineers_operator(tmp_path):
    reports = _stage(tmp_path)
    strict = _row("R-A", "area_um2", "<", 65018.219263)
    loose = _row("R-A", "area_um2", "<=", 65018.219263)
    assert sp.run(reports, [strict])[1]["requirements"][0]["met"] is False
    assert sp.run(reports, [loose])[1]["requirements"][0]["met"] is True


def test_run_no_targeted_rows_judges_nothing(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, [])
    assert rc == 0
    assert (
        data["requirements"] == [] and len(data["measurements"]) == 2
    )  # measured either way


def test_run_violated_slack(tmp_path):
    reports = _stage(tmp_path, qor=QOR_VIOLATED)
    rc, data = sp.run(reports, [_row("R-S", "timing_slack_ns", ">=", 0.0)])
    assert rc == 0
    assert data["requirements"][0]["met"] is False
    slack = [a for a in data["measurements"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(-0.5)


def test_run_unparseable_area_exit3(tmp_path):
    reports = _stage(tmp_path, area=AREA_NO_TOTAL)
    rc, payload = sp.run(reports, [])
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_unparseable_qor_exit3(tmp_path):
    reports = _stage(tmp_path, qor=QOR_NO_GROUP)
    rc, payload = sp.run(reports, [])
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_missing_report_exit1(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    assert sp.run(reports, []) == (1, None)


def test_run_returns_no_verdict_after_a_parse_failure(tmp_path):
    # was "removes the stale sidecar": the write-fresh-or-nothing guarantee now lives in the
    # return value — a failed parse yields no payload for build_result to fold.
    reports = _stage(tmp_path)
    assert sp.run(reports, [])[1] is not None
    (reports / "area.rpt").write_text(AREA_NO_TOTAL)
    assert sp.run(reports, []) == (3, None)


def test_run_wns_cross_check_contradiction_exit3(tmp_path):
    # negative per-group slack but a clean design summary -> exit 3
    reports = _stage(tmp_path, qor=QOR_CONTRADICT)
    rc, payload = sp.run(reports, [])
    assert rc == 3 and payload is None  # no verdict on a parse surprise


# ── finalize / build_result (v4 stage-CLI-tool) ───────────────────────────────
def _workdir(tmp_path, area=SAMPLE_AREA, qor=SAMPLE_QOR, netlist=True):
    """A completed run: reports/{area,qor}.rpt plus the netlist trio a pass requires.
    netlist=False stages the shape a failed dc_shell write leaves behind."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "area.rpt").write_text(area)
    (reports / "qor.rpt").write_text(qor)
    if netlist:
        (tmp_path / "out").mkdir(exist_ok=True)
        for ext in ("v", "sdc", "sdf"):
            (tmp_path / "out" / f"dut_top_syn.{ext}").write_text(f"{ext} content")
    return tmp_path


def test_build_result_pass_lean_shape(tmp_path):
    wd = _workdir(tmp_path)
    assert sp.build_result(wd, [], []) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "synthesis"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    assert ss["requirements"] == []
    assert (
        "notes" not in ss and "power_report" not in ss
    )  # lean shape: dropped fields absent
    assert "rtl_filelist" not in ss and "timing_exceptions" not in ss


def test_build_result_tooling_fail_on_unparseable(tmp_path):
    wd = _workdir(tmp_path, area=AREA_NO_TOTAL)  # parser run() returns 3
    assert sp.build_result(wd, [], []) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "synthesis report unparseable"


def test_declared_failure_wins_over_a_clean_gate(tmp_path):
    # A crash after the reports landed: they parse clean, so the gate would say pass.
    # Supplying the cause IS the declaration of failure.
    wd = _workdir(tmp_path)
    assert (
        sp.build_result(
            wd,
            [AREA_OK],
            [],
            fix_owner="rtl-design",
            fail_reason="dc_shell segfaulted after write_sdf",
        )
        == 0
    )
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert ss["fail_reason"] == "dc_shell segfaulted after write_sdf"
    assert ss["fix_owner"] == "rtl-design"
    # the gate did not run, so no numbers or verdicts are invented for a run that has none
    assert "measurements" not in ss and "requirements" not in ss


def test_declared_failure_needs_a_reason(tmp_path):
    wd = _workdir(tmp_path)
    assert sp.finalize(wd, [], [], fail_reason="   ") == 2
    assert not (wd / "result.json").exists()  # BLOCKED writes nothing


def test_finalize_cli_declared_infra_failure(tmp_path):
    # The license path: DC never ran, so there are no reports to grade at all.
    wd = tmp_path
    _spec(tmp_path, [])
    MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--fail-reason",
            "DC license missing: dc_shell exited with LICENSE_ERROR",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert "LICENSE_ERROR" in ss["fail_reason"]


def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps build_result: any internal raise -> exit 2 (BLOCKED),
    # never status=fail. (The old main() had this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(sp, "build_result", boom)
    assert sp.finalize(tmp_path, [], []) == 2


# ── reproducibility header: the DC version, which nothing else records ────────
def test_parse_tool_from_report_version():
    assert sp.parse_tool("Version: L-2016.03-SP1\n") == "Design Compiler L-2016.03-SP1"
    assert sp.parse_tool("no version here") == "Design Compiler unknown"


# ── artifacts[] enumeration (present-only, no self-listing) ───────────────────
def test_enumerate_artifacts_present_only_no_self(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "scripts").mkdir()
    for rel in ["out/dut_top_syn.v", "reports/area.rpt", "constraints.sdc"]:
        (tmp_path / rel).write_text("x")
    (tmp_path / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in sp.enumerate_artifacts(tmp_path)]
    assert "out" in paths and "reports/area.rpt" in paths
    assert "constraints.sdc" in paths
    assert "result.json" not in paths
    assert all((tmp_path / p).exists() for p in paths)  # only what is there


def test_enumerate_artifacts_delivers_the_out_tree_whatever_dc_named_inside_it(
    tmp_path,
):
    # The netlist trio is whatever dc_shell wrote, so no caller-supplied top name can
    # drop it: `out/` leaves as one tree, so whatever name dc_shell wrote inside it is
    # delivered — the netlist cannot fall out of artifacts[] because a name was unexpected.
    for rel in ("out/whatever_dc_wrote_syn.v", "out/whatever_dc_wrote_syn.sdc"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    paths = {a["path"] for a in sp.enumerate_artifacts(tmp_path)}
    assert paths == {"out"}


# ── golden: lean shape against a real run ─────────────────────────────────────
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthesis-golden"


def test_golden_lean_against_a_real_run(tmp_path):
    import shutil

    wd = tmp_path / "synthesis"
    shutil.copytree(_FIXTURE, wd)
    assert sp.build_result(wd, [AREA_OK], []) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    assert ss["requirements"] == [
        {
            "id": "R-A",
            "met": True,
            "actual": pytest.approx(70684.185148),
            "measured": AREA_SRC,
        }
    ]
    assert ss["tool"] == "Design Compiler L-2016.03-SP1"  # report header, NOT "dc2016"
    for k in ("top_module", "lib_db", "clock", "violations"):
        assert k not in ss  # recorded elsewhere, or retired
    for k in ("rtl_filelist", "power_report", "timing_exceptions", "notes"):
        assert k not in ss
    paths = [a["path"] for a in env["artifacts"]]
    assert "out" in paths and "reports/area.rpt" in paths
    assert "result.json" not in paths
    assert env["produced_at"].endswith("Z")


def test_golden_is_schema_valid(tmp_path):
    # Validate the in-memory envelope against {envelope schema + synthesis
    # result.schema} via Registry — inlined to pin the synthesis schema explicitly.
    import shutil

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    wd = tmp_path / "synthesis"
    shutil.copytree(_FIXTURE, wd)
    sp.build_result(wd, [AREA_OK, SLACK_OK], [])
    env = json.loads((wd / "result.json").read_text())
    env_schema = json.loads(
        (REPO_ROOT / "framework/references/schemas/envelope.schema.json").read_text()
    )
    stage_schema = json.loads(
        (REPO_ROOT / "skills/synthesis/references/result.schema.json").read_text()
    )
    registry = Registry().with_resource(
        "https://veripower.local/schemas/envelope.schema.json",
        Resource.from_contents(env_schema),
    )
    Draft202012Validator(stage_schema, registry=registry).validate(
        env
    )  # raises on invalid


def test_finalize_cli_happy_path(tmp_path):
    # End-to-end through _cmd_finalize (handler import + arg mapping), not just
    # in-process build_result.
    wd = _workdir(tmp_path)
    _spec(tmp_path, [AREA_OK])
    MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"]) == ("synthesis", "pass")
    assert env["stage_specific"]["requirements"][0]["id"] == "R-A"


# ── the rows requirements.json assigns to synthesis ───────────────────────────
def _cli(wd, *extra):
    MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
    return subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(wd), *extra],
        capture_output=True,
        text=True,
    )


def test_finalize_cli_reads_the_ledger_from_dispatch(tmp_path):
    # Only the rows judged by synthesis are this stage's; a power bound is not.
    wd = _workdir(tmp_path)
    power = _row("R-P", "power_mw", "<=", 5.0, judge="power-analysis")
    _spec(tmp_path, [AREA_TINY, power])
    r = _cli(wd, "--fix-owner", "rtl-design")
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert ss["requirements"] == [
        {
            "id": "R-A",
            "met": False,
            "actual": pytest.approx(65018.219263),
            "measured": AREA_SRC,
        }
    ]
    assert ss["fail_reason"] == "requirement(s) not met: R-A"


def test_finalize_cli_no_synthesis_rows_judges_nothing(tmp_path):
    # An engineer who set no bound synthesis measures gets a pass that says so: the empty
    # requirements[] is the record, not a skipped gate.
    wd = _workdir(tmp_path)
    _spec(tmp_path, [_row("R-P", "power_mw", "<=", 5.0, judge="power-analysis")])
    r = _cli(wd)
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass" and env["stage_specific"]["requirements"] == []


def test_a_row_without_a_target_takes_the_agents_verdict(tmp_path):
    # A budget in a unit DC does not report: the agent converts and declares.
    wd = _workdir(tmp_path)
    _spec(tmp_path, [AREA_OK, NAND2])
    declared = json.dumps(
        [
            {
                "id": "R-N",
                "met": True,
                "actual": "248.6K NAND2-eq at 2.8224 um2/gate",
                "measured": "read from the run's own report",
            }
        ]
    )
    r = _cli(wd, "--requirements", declared)
    assert r.returncode == 0, r.stderr
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert [e["id"] for e in ss["requirements"]] == ["R-A", "R-N"]  # ledger order
    assert ss["requirements"][1]["actual"].startswith("248.6K")


def test_an_undeclared_row_is_blocked(tmp_path):
    # A row the agent never read cannot pass as silence.
    wd = _workdir(tmp_path)
    _spec(tmp_path, [AREA_OK, NAND2])
    r = _cli(wd)
    assert r.returncode == 2
    assert "R-N" in r.stderr and not (wd / "result.json").exists()


def test_a_declared_miss_fails_the_run(tmp_path):
    wd = _workdir(tmp_path)
    _spec(tmp_path, [NAND2])
    r = _cli(
        wd,
        "--requirements",
        json.dumps(
            [
                {
                    "id": "R-N",
                    "met": False,
                    "actual": "0.48M NAND2-eq",
                    "measured": "read from the run's own report",
                }
            ]
        ),
        "--fix-owner",
        "rtl-design",
    )
    assert r.returncode == 0, r.stderr
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert (
        ss["fail_reason"] == "requirement(s) not met: R-N"
        and ss["fix_owner"] == "rtl-design"
    )


# ── netlist presence: a clean gate is not a met gate ───────────────────────────
def test_pass_requires_the_full_netlist_trio(tmp_path):
    # dc_run.tcl reports before it writes, and no write is return-checked, so a clean
    # reports/ can sit next to no netlist at all.
    wd = _workdir(tmp_path, netlist=False)
    assert sp.build_result(wd, [], []) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert "out/*_syn.v" in ss["fail_reason"] and "out/*_syn.sdf" in ss["fail_reason"]
    # Each verdict names the report line behind it; nothing else travels beside them.
    assert all(v["measured"] for v in ss["requirements"])


def test_partial_netlist_names_only_what_is_absent(tmp_path):
    wd = _workdir(tmp_path, netlist=False)
    (wd / "out").mkdir()
    (wd / "out" / "m_syn.v").write_text("netlist")
    (wd / "out" / "m_syn.sdc").write_text("sdc")
    assert sp.build_result(wd, [], []) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "netlist incomplete: dc_shell wrote no out/*_syn.sdf"


def test_missing_netlist_outranks_a_missed_row(tmp_path):
    wd = _workdir(tmp_path, netlist=False)
    assert sp.build_result(wd, [AREA_TINY], [], fix_owner="rtl-design") == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["requirements"][0]["met"] is False  # the miss is still on the record
    assert "netlist incomplete" in ss["fail_reason"]
    assert ss["fix_owner"] == "rtl-design"


def test_uninit_slack_is_unparseable_not_a_pass(tmp_path):
    # An unconstrained run is what bootstrap's fail-closed exists to prevent; when one gets
    # this far the parser must refuse it rather than read `uninit` as a number or as zero.
    reports = _stage(tmp_path, qor=QOR_UNINIT)
    assert sp.run(reports, [SLACK_OK]) == (3, None)


def test_uninit_group_does_not_shadow_a_constrained_one(tmp_path):
    reports = _stage(tmp_path, qor=QOR_UNINIT_PLUS_REAL)
    rc, data = sp.run(reports, [_row("R-S", "timing_slack_ns", ">=", 0.0)])
    assert rc == 0 and data["requirements"][0]["met"] is True
    slack = [a for a in data["measurements"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(6.51)
    assert "across 1 group(s)" in slack["source"]  # the uninit group is not counted
