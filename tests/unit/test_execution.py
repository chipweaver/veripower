"""Observe stage entrypoints; no shared runner API is assumed."""

import importlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def prepare(tmp_path, stage, mode):
    pkg, tool = (
        ("synthesis", "dc_shell") if stage == "synthesis" else ("timing", "pt_shell")
    )
    wd = tmp_path / "current"
    wd.mkdir()
    (wd / "config.tcl").write_text("# configured inputs\n")
    (wd / "extra").mkdir()
    (wd / "extra/settings.txt").write_text("authored input")
    if stage == "synthesis":
        (wd / "scripts").mkdir()
        (wd / "work").mkdir()
        (wd / "work/stale").write_text("old compiled design")
        (wd / "scripts/dc_run.tcl").write_text("# stage calculation\n")
        for name in ("constraints.sdc", "constraints.local.sdc"):
            (wd / name).write_text("# constraints\n")
        product = "reports/qor.rpt"
        body = (
            f"source = Path({str(ROOT / 'tests/unit/fixtures/synthesis-reports')!r})\n"
            "assert not Path('work/stale').exists()\n"
            "shutil.copytree(source/'reports', Path('reports'))\n"
            "shutil.copytree(source/'out', Path('out'))\n"
        )
        if mode == "partial":
            body += "Path('reports/area.rpt').unlink()\n"
    else:
        (wd / "run_sta.tcl").write_text("# stage calculation\n")
        product = "timing-report.txt"
        source = ROOT / "tests/unit/fixtures/timing-reports/timing-report.txt"
        body = (
            f"shutil.copy2({str(source)!r}, 'timing-report.txt')\n"
            "Path('reports').mkdir()\nPath('reports/constraints.rpt').write_text('new constraints')\n"
        )
        if mode == "partial":
            body += "Path('timing-report.txt').write_text('interrupted')\n"
    if stage == "timing-analysis":
        (wd / "reports").mkdir()
        (wd / "reports/constraints.rpt").write_text("old constraints")
    (wd / "result.json").write_text('{"status":"pass"}')
    (wd / "run.log").write_text("old success")
    target = wd / product
    target.parent.mkdir(exist_ok=True)
    target.write_text("old report")
    binary = tmp_path / "bin"
    binary.mkdir()
    code = (
        "#!/usr/bin/env python3\nfrom pathlib import Path\nimport shutil,time\n" + body
    )
    code += "assert Path('extra/settings.txt').read_text() == 'authored input'\n"
    code += "Path('config.tcl').write_text('attempt copy only')\n"
    if mode == "tool-error":
        code += "print('Error: failed calculation')\n"
    if mode == "exit":
        code += "raise SystemExit(7)\n"
    if mode == "interrupt":
        code += "Path('started').touch()\ntime.sleep(30)\n"
    (binary / tool).write_text(code)
    (binary / tool).chmod(0o755)
    command = [
        sys.executable,
        str(ROOT / f"skills/{stage}/scripts/{pkg}/__main__.py"),
        "run",
        "--workdir",
        str(wd),
    ]
    env = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]}
    return wd, product, command, env


@pytest.mark.parametrize("stage", ["synthesis", "timing-analysis"])
@pytest.mark.parametrize("mode", ["success", "exit", "tool-error", "partial"])
def test_only_completed_measurements_are_published(tmp_path, stage, mode):
    wd, product, command, env = prepare(tmp_path, stage, mode)
    rc = subprocess.run(command, env=env, capture_output=True, text=True).returncode
    assert (rc == 0) == (mode == "success")
    assert not (wd / "result.json").exists()
    assert (wd / "config.tcl").read_text() == "# configured inputs\n"
    if mode == "success":
        assert (wd / product).is_file()
        assert not (wd / ".pending").exists()
        if stage == "timing-analysis":
            assert (wd / "reports/constraints.rpt").read_text() == "new constraints"

    else:
        assert not (wd / product).exists()
        assert not (wd / "reports").exists()


@pytest.mark.parametrize("stage", ["synthesis", "timing-analysis"])
def test_interruption_does_not_publish_partial_outputs(tmp_path, stage):
    wd, product, command, env = prepare(tmp_path, stage, "interrupt")
    process = subprocess.Popen(
        command, env=env, start_new_session=True, stdout=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 5
        while not (wd / ".pending/started").exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=5)
    assert not (wd / product).exists()
    assert not (wd / "result.json").exists()
    assert (wd / ".pending" / product).is_file()


@pytest.mark.parametrize("stage", ["synthesis", "timing-analysis"])
def test_publication_failure_cannot_expose_a_truncated_report(
    tmp_path, monkeypatch, stage
):
    wd, product, unused, env = prepare(tmp_path, stage, "success")
    monkeypatch.setenv("PATH", env["PATH"])
    pkg = "synthesis" if stage == "synthesis" else "timing"
    monkeypatch.syspath_prepend(str(ROOT / f"skills/{stage}/scripts"))
    module = importlib.import_module(pkg + ".execute")
    replace = Path.replace

    def _interrupted(source, destination):
        if source.name == ("reports" if stage == "synthesis" else "timing-report.txt"):
            raise OSError("publication interrupted")
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", _interrupted)
    with pytest.raises(OSError, match="publication interrupted"):
        module.run(wd)
    assert not (wd / product).exists()
    assert not (wd / "result.json").exists()
    assert (wd / ".pending" / product).is_file()


@pytest.mark.parametrize("mode", ["success", "exit"])
def test_synthesis_can_remeasure_carried_implementation(tmp_path, mode):
    wd, product, command, env = prepare(tmp_path, "synthesis", mode)
    (wd / "out").mkdir()
    netlist = wd / "out/original.v"
    netlist.write_text("fixed implementation")
    tool = tmp_path / "bin/dc_shell"
    tool.write_text(
        tool.read_text().replace(
            "import shutil,time",
            f"import shutil,time\nassert Path({str(netlist)!r}).read_text() == 'fixed implementation'",
        )
    )
    completed = subprocess.run(command, env=env, capture_output=True, text=True)
    assert (completed.returncode == 0) == (mode == "success")
    if mode == "exit":
        assert netlist.read_text() == "fixed implementation"
        assert not (wd / product).exists()
