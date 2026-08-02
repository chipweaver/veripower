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


def _stage(tmp_path, area=SAMPLE_AREA, qor=SAMPLE_QOR):
    """Write reports/{area,qor}.rpt under tmp_path; return (reports_dir, out_path)."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "area.rpt").write_text(area)
    (reports / "qor.rpt").write_text(qor)
    return reports


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
    rc, data = sp.run(reports, None, None)
    assert rc == 0
    slack = [a for a in data["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(0.95)
    assert slack["value"] != pytest.approx(16.99)


def test_run_area_disambiguation(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, None, None)
    assert rc == 0
    area = [a for a in data["ppa_actual"] if a["dim"] == "area_um2"][0]
    assert area["value"] == pytest.approx(65018.219263)


def test_run_verdict_pass(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, 70000.0, 0.5)
    assert rc == 0
    assert data["verdict"] == "pass"
    assert data["violations"] == []


def test_run_verdict_fail_ppa_exit0(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, None, 2.0)
    assert rc == 0  # PPA miss is still exit 0
    assert data["verdict"] == "fail"
    assert data["violations"] == [
        {"dim": "timing_slack_ns", "target": 2.0, "actual": pytest.approx(0.95)}
    ]


def test_run_no_targets_vacuous_pass(tmp_path):
    reports = _stage(tmp_path)
    rc, data = sp.run(reports, None, None)
    assert rc == 0
    assert data["verdict"] == "pass"
    assert data["violations"] == []


def test_run_violated_slack(tmp_path):
    reports = _stage(tmp_path, qor=QOR_VIOLATED)
    rc, data = sp.run(reports, None, 0.0)
    assert rc == 0
    assert data["verdict"] == "fail"
    slack = [a for a in data["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(-0.5)


def test_run_unparseable_area_exit3(tmp_path):
    reports = _stage(tmp_path, area=AREA_NO_TOTAL)
    rc, payload = sp.run(reports, None, None)
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_unparseable_qor_exit3(tmp_path):
    reports = _stage(tmp_path, qor=QOR_NO_GROUP)
    rc, payload = sp.run(reports, None, None)
    assert rc == 3 and payload is None  # no verdict on a parse surprise


def test_run_missing_report_exit1(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    assert sp.run(reports, None, None) == (1, None)


def test_run_returns_no_verdict_after_a_parse_failure(tmp_path):
    # was "removes the stale sidecar": the write-fresh-or-nothing guarantee now lives in the
    # return value — a failed parse yields no payload for build_result to fold.
    reports = _stage(tmp_path)
    assert sp.run(reports, None, None)[1] is not None
    (reports / "area.rpt").write_text(AREA_NO_TOTAL)
    assert sp.run(reports, None, None) == (3, None)


def test_run_wns_cross_check_contradiction_exit3(tmp_path):
    # negative per-group slack but a clean design summary -> exit 3 (review S3)
    reports = _stage(tmp_path, qor=QOR_CONTRADICT)
    rc, payload = sp.run(reports, None, None)
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
            (tmp_path / "out" / f"tpu_top_syn.{ext}").write_text(f"{ext} content")
    return tmp_path


def test_build_result_pass_lean_shape(tmp_path):
    wd = _workdir(tmp_path)
    assert sp.build_result(wd, area_target=None, slack_target=None) == 0
    env = json.loads((wd / "result.json").read_text())
    assert env["stage"] == "synthesis"
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    slack = [a for a in ss["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(0.95)  # parser regression: min across groups
    assert ss["violations"] == []
    assert (
        "notes" not in ss and "power_report" not in ss
    )  # lean shape: dropped fields absent
    assert "rtl_filelist" not in ss and "timing_exceptions" not in ss


def test_build_result_tooling_fail_on_unparseable(tmp_path):
    wd = _workdir(tmp_path, area=AREA_NO_TOTAL)  # parser run() returns 3
    assert sp.build_result(wd, area_target=None, slack_target=None) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "synthesis report unparseable"


def test_declared_failure_wins_over_a_clean_gate(tmp_path):
    # A crash after the reports landed: they parse clean, so the gate would say pass.
    # Supplying the cause IS the declaration of failure.
    wd = _workdir(tmp_path)
    assert (
        sp.build_result(
            wd,
            area_target=None,
            slack_target=None,
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
    # the gate did not run, so no PPA numbers are invented for a run that has none
    assert "ppa_actual" not in ss and "violations" not in ss


def test_declared_failure_needs_a_reason(tmp_path):
    wd = _workdir(tmp_path)
    assert sp.finalize(wd, None, None, fail_reason="   ") == 2
    assert not (wd / "result.json").exists()  # BLOCKED writes nothing


def test_finalize_cli_declared_infra_failure(tmp_path):
    # The license path: DC never ran, so there are no reports to grade at all.
    wd = tmp_path
    (wd / "dispatch.json").write_text(json.dumps({"inputs": {"ppa": str(tmp_path)}}))
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
    assert sp.finalize(tmp_path, "m", None, None) == 2


# ── reproducibility header: the DC version, which nothing else records ────────
def test_parse_tool_from_report_version():
    assert sp.parse_tool("Version: L-2016.03-SP1\n") == "Design Compiler L-2016.03-SP1"
    assert sp.parse_tool("no version here") == "Design Compiler unknown"


# ── artifacts[] enumeration (present-only, no self-listing) ───────────────────
def test_enumerate_artifacts_present_only_no_self(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "scripts").mkdir()
    for rel in ["out/tpu_top_syn.v", "reports/area.rpt", "constraints.sdc"]:
        (tmp_path / rel).write_text("x")
    (tmp_path / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in sp.enumerate_artifacts(tmp_path)]
    assert "out/tpu_top_syn.v" in paths and "reports/area.rpt" in paths
    assert "constraints.sdc" in paths
    assert "result.json" not in paths
    assert all((tmp_path / p).is_file() for p in paths)  # only present files


def test_enumerate_artifacts_matches_netlist_by_glob_not_by_a_passed_name(tmp_path):
    # The netlist trio is whatever dc_shell wrote, so no caller-supplied top name can
    # drop it: an omitted out/*_syn.v is a pass promoted with no netlist, leaving
    # timing-analysis and power-analysis undispatchable.
    (tmp_path / "out").mkdir()
    (tmp_path / "reports").mkdir()
    for rel in ("out/whatever_dc_wrote_syn.v", "out/whatever_dc_wrote_syn.sdc"):
        (tmp_path / rel).write_text("x")
    paths = [a["path"] for a in sp.enumerate_artifacts(tmp_path)]
    assert "out/whatever_dc_wrote_syn.v" in paths
    assert "out/whatever_dc_wrote_syn.sdc" in paths
    assert "out/whatever_dc_wrote_syn.sdf" not in paths  # present-only, never invented


# ── golden: lean shape against the real tpu_top run ───────────────────────────
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthesis-tpu_top"


def test_golden_lean_against_real_tpu_top(tmp_path):
    import shutil

    wd = tmp_path / "synthesis"
    shutil.copytree(_FIXTURE, wd)
    assert sp.build_result(wd, area_target=None, slack_target=None) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "pass"
    area = [a for a in ss["ppa_actual"] if a["dim"] == "area_um2"][0]["value"]
    slack = [a for a in ss["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]["value"]
    assert area == pytest.approx(70684.185148) and slack == pytest.approx(0.73)
    assert ss["violations"] == []
    assert ss["tool"] == "Design Compiler L-2016.03-SP1"  # report header, NOT "dc2016"
    for k in ("top_module", "lib_db", "clock", "ppa_targets"):
        assert (
            k not in ss
        )  # recorded elsewhere: kernel identity record, ppa.json, artifacts[]
    for k in ("rtl_filelist", "power_report", "timing_exceptions", "notes"):
        assert k not in ss
    paths = [a["path"] for a in env["artifacts"]]
    assert "out/tpu_top_syn.v" in paths and "reports/area.rpt" in paths
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
    sp.build_result(wd, area_target=None, slack_target=None)
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
    wd = _workdir(
        tmp_path
    )  # stages reports/{area,qor}.rpt (constraints/config optional)
    # finalize reads PPA targets via the injected dispatch.json "ppa" key (no
    # sibling ppa.json here -> vacuous empty targets, same as the old absent-file
    # default).
    (wd / "dispatch.json").write_text(
        json.dumps({"inputs": {"ppa": str(tmp_path / "no-ppa")}})
    )
    MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"]) == ("synthesis", "pass")


# ── PPA targets read from the injected dispatch.json "ppa" stage root ──────────
def test_finalize_cli_reads_ppa_json_sibling(tmp_path):
    # No --area-target/--slack-target flags exist anymore: finalize reads the
    # PPA gate straight from the specification stage root's ppa.json, whose
    # location comes from the injected dispatch.json "ppa" key (not self-nav).
    module_root = tmp_path / "asic" / "tpu_top"
    wd = module_root / "Design" / "synthesis" / "runs" / "1"
    wd.mkdir(parents=True)
    reports = wd / "reports"
    reports.mkdir()
    (reports / "area.rpt").write_text(SAMPLE_AREA)
    (reports / "qor.rpt").write_text(SAMPLE_QOR)
    (wd / "out").mkdir()  # a complete run, so the fail below is the PPA gate's
    for ext in ("v", "sdc", "sdf"):
        (wd / "out" / f"tpu_top_syn.{ext}").write_text(ext)
    spec_dir = module_root / "Design" / "specification"
    spec_dir.mkdir(parents=True)
    (spec_dir / "ppa.json").write_text(
        json.dumps(
            [
                {"dim": "area_um2", "target": 1.0},  # unreachable -> forces a fail
                {"dim": "power_mw", "target": 5.0},  # not a synthesis dim -> ignored
            ]
        )
    )
    (wd / "dispatch.json").write_text(json.dumps({"inputs": {"ppa": str(spec_dir)}}))
    MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert ss["violations"] == [
        {"dim": "area_um2", "target": 1.0, "actual": pytest.approx(65018.219263)}
    ]


def test_finalize_cli_no_ppa_json_is_vacuous_pass(tmp_path):
    # No sibling ppa.json at all (e.g. a first-ever run) -> [] targets, same as
    # the old no-flags-passed default; never a crash. dispatch.json (as kernel
    # dispatch would inject it) is present; its "ppa" target just has no ppa.json.
    module_root = tmp_path / "asic" / "tpu_top"
    wd = module_root / "Design" / "synthesis" / "runs" / "1"
    wd.mkdir(parents=True)
    reports = wd / "reports"
    reports.mkdir()
    (reports / "area.rpt").write_text(SAMPLE_AREA)
    (reports / "qor.rpt").write_text(SAMPLE_QOR)
    (wd / "out").mkdir()
    for ext in ("v", "sdc", "sdf"):
        (wd / "out" / f"tpu_top_syn.{ext}").write_text(ext)
    spec_dir = module_root / "Design" / "specification"
    (wd / "dispatch.json").write_text(json.dumps({"inputs": {"ppa": str(spec_dir)}}))
    MAIN = REPO_ROOT / "skills/synthesis/scripts/synthesis/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = json.loads((wd / "result.json").read_text())
    assert env["status"] == "pass"


# ── netlist presence: a clean gate is not a met gate ───────────────────────────
def test_pass_requires_the_full_netlist_trio(tmp_path):
    # dc_run.tcl reports before it writes, and no write is return-checked, so a clean
    # reports/ can sit next to no netlist at all.
    wd = _workdir(tmp_path, netlist=False)
    assert sp.build_result(wd, area_target=None, slack_target=None) == 0
    env = json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    assert env["status"] == "fail"
    assert "out/*_syn.v" in ss["fail_reason"] and "out/*_syn.sdf" in ss["fail_reason"]
    assert ss["ppa_actual"]  # the measured numbers are still recorded


def test_partial_netlist_names_only_what_is_absent(tmp_path):
    wd = _workdir(tmp_path, netlist=False)
    (wd / "out").mkdir()
    (wd / "out" / "m_syn.v").write_text("netlist")
    (wd / "out" / "m_syn.sdc").write_text("sdc")
    assert sp.build_result(wd, area_target=None, slack_target=None) == 0
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["fail_reason"] == "netlist incomplete: dc_shell wrote no out/*_syn.sdf"


def test_missing_netlist_outranks_a_ppa_miss(tmp_path):
    wd = _workdir(tmp_path, netlist=False)
    assert (
        sp.build_result(
            wd,
            area_target=1.0,  # unreachable -> the gate fails too
            slack_target=None,
            fix_owner="rtl-design",
        )
        == 0
    )
    ss = json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["violations"]  # the PPA miss is still on the record
    assert ss["fix_owner"] == "rtl-design"


def test_uninit_slack_is_unparseable_not_a_pass(tmp_path):
    # An unconstrained run is what bootstrap's fail-closed exists to prevent; when one gets
    # this far the parser must refuse it rather than read `uninit` as a number or as zero.
    reports = _stage(tmp_path, qor=QOR_UNINIT)
    assert sp.run(reports, None, 0.0) == (3, None)


def test_uninit_group_does_not_shadow_a_constrained_one(tmp_path):
    reports = _stage(tmp_path, qor=QOR_UNINIT_PLUS_REAL)
    rc, data = sp.run(reports, None, 0.0)
    assert rc == 0 and data["verdict"] == "pass"
    slack = [a for a in data["ppa_actual"] if a["dim"] == "timing_slack_ns"][0]
    assert slack["value"] == pytest.approx(6.51)
    assert "across 1 group(s)" in slack["source"]  # the uninit group is not counted
