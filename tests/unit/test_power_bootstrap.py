"""Power setup and execution boundaries, exercised through the public CLI."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/power-analysis/scripts/power/__main__.py"


def invoke(wd, verb):
    return subprocess.run(
        ["python3", str(MAIN), verb, "--workdir", str(wd)],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def workdir(tmp_path):
    syn = tmp_path / "synthesis" / "out"
    syn.mkdir(parents=True)
    for ext in ("v", "sdc", "sdf"):
        (syn / f"device_syn.{ext}").write_text("input")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "verification-plan.md").write_text("Clock-off and active measurements.")
    (plan / "power-scenarios.json").write_text('[{"id":"idle"},{"id":"busy"}]')
    wd = tmp_path / "power run"
    wd.mkdir()
    (wd / "dispatch.json").write_text(
        json.dumps({"inputs": {"netlist": str(syn.parent), "plan": str(plan)}})
    )
    return wd


def test_bootstrap_without_functional_tb_and_preserves_authored_work(workdir):
    r = invoke(workdir, "bootstrap")
    assert r.returncode == 0, r.stderr
    script = workdir / "experiment" / "run.sh"
    script.write_text("authored experiment")
    (workdir / "env.sh").write_text("authored setup")
    assert invoke(workdir, "bootstrap").returncode == 0
    assert script.read_text() == "authored experiment"
    assert (workdir / "env.sh").read_text() == "authored setup"


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"id": "../escape"}],
        [{"id": "a"}, {"id": "a"}],
        [{"id": "a", "sequence_ref": "s"}],
    ],
)
def test_invalid_plan_does_not_deploy(workdir, rows):
    inputs = json.loads((workdir / "dispatch.json").read_text())["inputs"]
    (Path(inputs["plan"]) / "power-scenarios.json").write_text(json.dumps(rows))
    assert invoke(workdir, "bootstrap").returncode != 0
    assert not (workdir / "env.sh").exists()


def test_missing_plan_meaning_does_not_deploy(workdir):
    inputs = json.loads((workdir / "dispatch.json").read_text())["inputs"]
    (Path(inputs["plan"]) / "verification-plan.md").unlink()
    assert invoke(workdir, "bootstrap").returncode != 0
    assert not (workdir / "env.sh").exists()


def test_each_scenario_runs_fresh_and_zero_exit_cannot_inherit_pass(workdir):
    assert invoke(workdir, "bootstrap").returncode == 0
    script = workdir / "experiment/run.sh"
    script.write_text(
        'printf "%s" "$1" >"$2"\nprintf "PASS\\n" >"$3"\necho "$1" >> invocations\n'
    )
    assert invoke(workdir, "simulate").returncode == 0
    assert (workdir / "saif/idle.saif").read_text() == "idle"
    assert (workdir / "saif/busy.saif").read_text() == "busy"
    assert invoke(workdir, "simulate").returncode == 0
    assert (workdir / "invocations").read_text().splitlines() == ["idle", "busy"] * 2
    old = workdir / "reports_ptpx/idle"
    old.mkdir(parents=True)
    (old / "power_flat.rpt").write_text("old result")
    script.write_text("exit 0\n")
    assert invoke(workdir, "simulate").returncode == 1
    assert not old.exists()
    assert (workdir / "saif/idle.status").read_text().strip() == "FAIL"
    assert not (workdir / "saif/idle.saif").exists()


def test_nonzero_exit_overrides_written_pass(workdir):
    assert invoke(workdir, "bootstrap").returncode == 0
    (workdir / "experiment/run.sh").write_text(
        'echo activity >"$2"; echo PASS >"$3"; exit 1\n'
    )
    assert invoke(workdir, "simulate").returncode == 1
    assert (workdir / "saif/busy.status").read_text().strip() == "FAIL"


def test_calculation_does_not_run_experiment_or_accept_stale_reports(workdir):
    assert invoke(workdir, "bootstrap").returncode == 0
    (workdir / "experiment/run.sh").write_text("touch invoked\n")
    old = workdir / "reports_ptpx/idle"
    old.mkdir(parents=True)
    (old / "power_flat.rpt").write_text("old result")
    assert invoke(workdir, "calculate").returncode == 1
    assert not (workdir / "invoked").exists()
    assert not old.exists()


def test_failed_compilation_invalidates_prior_measurement(workdir):
    assert invoke(workdir, "bootstrap").returncode == 0
    (workdir / "saif").mkdir()
    (workdir / "saif/idle.saif").write_text("activity")
    (workdir / "saif/idle.status").write_text("PASS")
    (workdir / "result.json").write_text('{"status":"pass"}')
    reports = workdir / "reports_ptpx/idle"
    reports.mkdir(parents=True)
    (reports / "power_flat.rpt").write_text("old report")
    (workdir / "experiment/compile.sh").write_text("exit 1\n")
    assert invoke(workdir, "compile").returncode == 1
    assert not (workdir / "result.json").exists()
    assert not (workdir / "saif/idle.status").exists()
    assert not reports.exists()


def test_interrupted_calculation_does_not_publish_partial_report(workdir, monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT / "skills/power-analysis/scripts"))
    from power import execute

    assert invoke(workdir, "bootstrap").returncode == 0
    (workdir / "saif").mkdir()
    for sid in ("idle", "busy"):
        (workdir / "saif" / f"{sid}.saif").write_text("activity")
        (workdir / "saif" / f"{sid}.status").write_text("PASS")

    def interrupted(command, **kwargs):
        (Path(kwargs["env"]["REPORTS_DIR"]) / "power_flat.rpt").write_text(
            "partial report"
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(execute.subprocess, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute.run(workdir, "calculate")
    assert not (workdir / "reports_ptpx/idle/power_flat.rpt").exists()
    assert (workdir / ".pending/idle/power_flat.rpt").exists()


def test_invalid_dispatch_cannot_leave_old_success(workdir):
    (workdir / "result.json").write_text('{"status":"pass"}')
    (workdir / "dispatch.json").write_text("{broken")
    assert invoke(workdir, "compile").returncode == 2
    assert not (workdir / "result.json").exists()


def test_bootstrap_needs_no_sdf_or_sdc_until_execution(workdir):
    inputs = json.loads((workdir / "dispatch.json").read_text())["inputs"]
    syn = Path(inputs["netlist"]) / "out"
    (syn / "device_syn.sdf").unlink()
    (syn / "device_syn.sdc").unlink()
    assert invoke(workdir, "bootstrap").returncode == 0
    assert not (workdir / "Makefile").exists()
    assert not (workdir / "gls-compile-log.txt").exists()


def test_simulation_entry_never_invokes_compilation(workdir):
    assert invoke(workdir, "bootstrap").returncode == 0
    (workdir / "experiment/compile.sh").write_text("touch compiled; exit 1\n")
    (workdir / "experiment/run.sh").write_text('echo activity >"$2"; echo PASS >"$3"\n')
    assert invoke(workdir, "simulate").returncode == 0
    assert not (workdir / "compiled").exists()
    assert not (workdir / "gls-compile-log.txt").exists()


@pytest.mark.parametrize("message", ["", "Error: invalid calculation setting\n"])
def test_pt_error_with_zero_exit_is_not_published(workdir, monkeypatch, message):
    import sys

    sys.path.insert(0, str(ROOT / "skills/power-analysis/scripts"))
    from power import execute

    assert invoke(workdir, "bootstrap").returncode == 0
    (workdir / "saif").mkdir()
    for sid in ("idle", "busy"):
        (workdir / "saif" / f"{sid}.saif").write_text("activity")
        (workdir / "saif" / f"{sid}.status").write_text("PASS")

    def calculate(command, **kwargs):
        (Path(kwargs["env"]["REPORTS_DIR"]) / "power_flat.rpt").write_text("report")
        kwargs["stdout"].write(message)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(execute.subprocess, "run", calculate)
    assert execute.run(workdir, "calculate") == int(bool(message))
    for sid in ("idle", "busy"):
        assert (workdir / f"reports_ptpx/{sid}/power_flat.rpt").exists() == (
            not message
        )
        if message:
            assert (workdir / f".pending/{sid}/power_flat.rpt").is_file()
