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


# ── Task 1: B3 invariant tolerance ────────────────────────────────────────────


def test_invariant_tolerates_4sigfig_rounding(tmp_path):
    # Real PrimeTime PX format: "Dynamic Power Units = 1 W" (no inline unit on summary lines).
    # Values are in W; _resolve_mw converts to mW (multiply by 1000).
    # After conversion: Total=1.653 mW, sum=1.652940 mW, diff=6.0e-5 mW.
    # 6.0e-5 > _EPS_MW (1e-6) → trips the invariant AS-IS, but << 1% of total → must NOT flag.
    wd = tmp_path / "wd"
    (wd / "saif").mkdir(parents=True)
    (wd / "saif" / "S1.saif").write_text("x" * 100)
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
    plan = tmp_path / "plan.json"
    plan.write_text(
        _json.dumps(
            {
                "power_scenarios": [
                    {
                        "id": "S1",
                        "sequence_ref": "idle_seq",
                        "corner_intent": "TT@25C",
                        "duration_cycles": 2000,
                    }
                ]
            }
        )
    )
    out = wd / "power-actual.json"
    rc = p.run(plan, wd, "[]", out)
    data = _json.loads(out.read_text())
    # Before the fix: rc==1, failures[0].category=="ptpx_data" (invariant). After: clean pass.
    assert rc == 0, (
        f"4-sig-fig rounding must not trip the invariant; failures={data.get('failures')}"
    )
    assert data["verdict"] == "pass"
    assert data["failures"] == []


# ── Task 2: build_result + finalize subcommand ────────────────────────────────


def test_build_result_pass_lean_shape(tmp_path):
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    assert p.build_result(wd, module="tpu_top", plan_path=str(plan), targets="[]") == 0
    env = _json.loads((wd / "result.json").read_text())
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "power-analysis",
        "tpu_top",
    )
    assert env["status"] == "pass" and env["produced_at"].endswith("Z")
    ss = env["stage_specific"]
    # the 7 fields the sidecar carries fold straight through (minus verdict)
    assert "verdict" not in ss
    assert ss["ppa_gate_skipped"] is True  # targets="[]"
    assert ss["ppa_actual"][0]["value"] == pytest.approx(0.42)
    assert ss["compile_info"]["vcs_version"] == "L-2016.06_Full64"
    assert ss["violations"] == []
    assert "notes" not in ss  # lean shape: dropped field absent


def test_build_result_tooling_fail_on_invariant(tmp_path):
    # A report whose Total != sum(components) by >> 1% (the parser's invariant)
    # -> parser exit 1 -> build_result writes failure_kind=tooling + failures[].
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(9.99, 0.05, 0.02, 0.35)},
    )  # deliberately off
    assert p.build_result(wd, module="tpu_top", plan_path=str(plan), targets="[]") == 0
    ss = _json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["failure_kind"] == "tooling"
    assert ss["failures"] and ss["failures"][0]["category"] == "ptpx_data"
    assert isinstance(ss["fail_reason"], str) and ss["fail_reason"]


def test_build_result_ppa_miss(tmp_path):
    # the failure_kind=ppa branch of build_result: a scenario over target ->
    # status=fail + violations + ppa_actual (the schema's ppa-fail if/then).
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN,
        sizes={"S1": 2000, "S2": 4000},
        flats={
            "S1": _flat_rpt(0.42, 0.05, 0.02, 0.35),
            "S2": _flat_rpt(1.85, 0.62, 0.95, 0.28),
        },
    )
    targets = _json.dumps([{"dim": "power_mw", "target": 1.2, "scenario_id": "S2"}])
    assert (
        p.build_result(wd, module="tpu_top", plan_path=str(plan), targets=targets) == 0
    )
    ss = _json.loads((wd / "result.json").read_text())["stage_specific"]
    assert ss["failure_kind"] == "ppa"
    assert ss["violations"] == [
        {
            "dim": "power_mw",
            "target": 1.2,
            "actual": pytest.approx(1.85),
            "scenario_id": "S2",
        }
    ]
    assert ss["ppa_actual"]  # required alongside violations on a ppa-fail
    assert isinstance(ss["fail_reason"], str) and ss["fail_reason"]


def test_finalize_blocked_on_internal_raise(tmp_path, monkeypatch):
    # finalize() wraps build_result: any internal raise -> exit 2 (BLOCKED), never
    # status=fail. (The old main() finalize branch had this except; it moves to finalize().)
    def boom(*a, **k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(p, "build_result", boom)
    assert p.finalize(tmp_path, "m", "scaffold.json", "[]") == 2


def test_finalize_missing_required_flag_is_blocked(tmp_path):
    MAIN = REPO_ROOT / "skills/power-analysis/scripts/power/__main__.py"
    # missing --module -> argparse exit 2
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --module
    # missing --scaffold -> argparse exit 2 (required; --ppa-targets is optional)
    r = subprocess.run(
        ["python3", str(MAIN), "finalize", "--workdir", str(tmp_path), "--module", "m"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2  # argparse: missing --scaffold


def test_finalize_cli_happy_path(tmp_path):
    # End-to-end through _cmd_finalize (lazy handler import + --scaffold/--ppa-targets
    # arg mapping), not just in-process build_result. A handler typo would pass every
    # other test (which call build_result directly) but fail here.
    wd, plan = _make_workdir(
        tmp_path,
        _SCEN[:1],
        sizes={"S1": 2000},
        flats={"S1": _flat_rpt(0.42, 0.05, 0.02, 0.35)},
    )
    MAIN = REPO_ROOT / "skills/power-analysis/scripts/power/__main__.py"
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "finalize",
            "--workdir",
            str(wd),
            "--module",
            "tpu_top",
            "--scaffold",
            str(plan),
            "--ppa-targets",
            "[]",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    env = _json.loads((wd / "result.json").read_text())
    assert (env["stage"], env["status"], env["module"]) == (
        "power-analysis",
        "pass",
        "tpu_top",
    )


# ── Task 4: artifacts[] enumeration ───────────────────────────────────────────


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
        "power-actual.json",
    ]:
        (wd / f).write_text("x")
    for d in ["scripts", "scaffold", "simv.daidir", "saif", "reports_ptpx"]:
        (wd / d).mkdir()
    (wd / "result.json").write_text("{}")  # must NOT self-list
    paths = [a["path"] for a in p.enumerate_artifacts(wd)]
    for expect in [
        "env.sh",
        "Makefile",
        "scripts",
        "saif",
        "reports_ptpx",
        "power-actual.json",
        "simv.daidir",
    ]:
        assert expect in paths
    assert "result.json" not in paths
    assert all((wd / pth).exists() for pth in paths)  # only present paths (file OR dir)


# ── Task 5: Golden test against the real tpu_top run ──────────────────────────


def test_golden_real_reports_lean_pass(tmp_path):
    import shutil

    ROOT = Path(__file__).resolve().parent / "fixtures" / "power-tpu_top"
    wd = tmp_path / "wd"
    shutil.copytree(ROOT / "real", wd)
    rc = p.build_result(
        wd, module="tpu_top", plan_path=str(ROOT / "plan.json"), targets="[]"
    )
    assert rc == 0
    env = _json.loads((wd / "result.json").read_text())
    ss = env["stage_specific"]
    # With B3 fixed (Task 1), the gate parses the real 4-sig-fig reports clean -> pass.
    assert (env["schema_version"], env["stage"], env["module"]) == (
        1,
        "power-analysis",
        "tpu_top",
    )
    assert env["status"] == "pass"
    assert env["produced_at"].endswith("Z")
    # the 7 stage_specific fields fold through verbatim from the clean sidecar (minus verdict)
    assert set(ss) >= {
        "saif_artifacts",
        "compile_info",
        "failures",
        "ppa_actual",
        "violations",
        "power_by_corner",
        "ppa_gate_skipped",
    }
    assert "verdict" not in ss
    assert ss["failures"] == []  # clean parse — no ptpx_data failures
    assert ss["violations"] == []  # targets="[]" -> ppa gate skipped
    assert ss["ppa_gate_skipped"] is True
    assert ss["compile_info"]["vcs_version"] == "L-2016.06_Full64"
    assert all(
        e["value"] is not None for e in ss["ppa_actual"]
    )  # every scenario parsed
    assert "notes" not in ss  # lean: dropped
    paths = [a["path"] for a in env["artifacts"]]
    assert "reports_ptpx" in paths and "power-actual.json" in paths
    assert "result.json" not in paths


def test_golden_is_schema_valid(tmp_path):
    # Canonical pattern: validate the in-memory dict against {envelope schema + this
    # stage's result.schema} via Registry (mirrors test_signoff_result.py pattern).
    import shutil

    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    ROOT = Path(__file__).resolve().parent / "fixtures" / "power-tpu_top"
    wd = tmp_path / "wd"
    shutil.copytree(ROOT / "real", wd)
    p.build_result(
        wd, module="tpu_top", plan_path=str(ROOT / "plan.json"), targets="[]"
    )
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
