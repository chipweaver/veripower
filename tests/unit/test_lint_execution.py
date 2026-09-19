"""Invalidate the checks actually selected by the effective launcher configuration."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("stage", ["lint", "cdc", "all"])
@pytest.mark.parametrize("source", ["env.sh", "caller"])
def test_only_selected_reports_are_withdrawn(tmp_path, stage, source):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "skills/lint-cdc/templates/scripts/run_spyglass.sh", scripts)
    (scripts / "run.tcl").write_text("# launcher input\n")
    (tmp_path / "env.sh").write_text(
        'export SPYGLASS_STAGE="${SPYGLASS_STAGE:-' + stage + '}"\n'
        if source == "env.sh"
        else 'export SPYGLASS_STAGE="${SPYGLASS_STAGE:-all}"\n'
    )
    for name in (
        "lint-report.txt",
        "cdc-report.txt",
        "lint-violations.json",
        "cdc-violations.json",
    ):
        (tmp_path / name).write_text("previous " + name)
    (tmp_path / "result.json").write_text('{"status":"pass"}')
    bindir = tmp_path / "bin"
    bindir.mkdir()
    tool = bindir / "spyglass"
    tool.write_text(
        '#!/bin/sh\nprintf "%s" "$SPYGLASS_STAGE" > selected-stage.txt\nexit 7\n'
    )
    tool.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "SPYGLASS_STAGE"}
    env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
    if source == "caller":
        env["SPYGLASS_STAGE"] = stage
    proc = subprocess.run(["bash", "scripts/run_spyglass.sh"], cwd=tmp_path, env=env)
    assert proc.returncode == 7
    assert (tmp_path / "selected-stage.txt").read_text() == stage
    assert not (tmp_path / "result.json").exists()
    for check in ("lint", "cdc"):
        for suffix in ("report.txt", "violations.json"):
            path = tmp_path / f"{check}-{suffix}"
            if stage in (check, "all"):
                assert not path.exists()
            else:
                assert path.read_text() == "previous " + path.name


@pytest.mark.parametrize(
    "setup", [". ./missing-site.sh", ": ${MISSING_SITE:?required}", "false", "exit 0"]
)
def test_incomplete_setup_cannot_republish_old_clean_summaries(tmp_path, setup):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "skills/lint-cdc/templates/scripts/run_spyglass.sh", scripts)
    (tmp_path / "env.sh").write_text(setup + "\nexport SPYGLASS_STAGE=lint\n")
    for check in ("lint", "cdc"):
        (tmp_path / f"{check}-report.txt").write_text("previous raw evidence")
        (tmp_path / f"{check}-violations.json").write_text("previous clean summary")
    (tmp_path / "Makefile").write_text(
        "all:\n\t@bash scripts/run_spyglass.sh\n\t@touch collector-ran\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "MISSING_SITE"}
    proc = subprocess.run(["make", "all"], cwd=tmp_path, env=env, capture_output=True)
    assert proc.returncode != 0
    assert not (tmp_path / "collector-ran").exists()
    for check in ("lint", "cdc"):
        assert not (tmp_path / f"{check}-violations.json").exists()
        assert (tmp_path / f"{check}-report.txt").read_text() == "previous raw evidence"
