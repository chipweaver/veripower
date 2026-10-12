"""Opt-in native adapter checks with local scripted responses, no model or EDA keys."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    os.environ.get("VERIPOWER_OPENCODE_TESTS") != "1",
    reason="opt-in OpenCode 2 runtime probe",
)
@pytest.mark.parametrize("policy", ["allow", "deny"])
def test_opencode_package_background_completion_and_permissions(tmp_path, policy):
    binary = os.environ.get("VERIPOWER_OPENCODE_BIN", "opencode")
    version = subprocess.check_output([binary, "--version"], text=True)
    assert "v2." in version, version
    packed = subprocess.run(
        ["npm", "pack", "--pack-destination", str(tmp_path), "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    package = tmp_path / json.loads(packed.stdout)[0]["filename"]
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "tests/runtime/opencode.py"),
            binary,
            str(package),
            str(tmp_path / "workspace"),
            policy,
        ],
        text=True,
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(
    "VERIPOWER_DSH_NODE_MODULES" not in os.environ,
    reason="opt-in published DeepSeek Harness runtime probe",
)
def test_dsh_native_registration_prompt_and_host_decisions(tmp_path):
    modules = Path(os.environ["VERIPOWER_DSH_NODE_MODULES"])
    fixture = tmp_path / "plugin"
    (fixture / ".dsh/plugins").mkdir(parents=True)
    shutil.copyfile(
        ROOT / ".dsh/plugins/veripower.js", fixture / ".dsh/plugins/veripower.js"
    )
    (fixture / "skills").symlink_to(ROOT / "skills", target_is_directory=True)
    (fixture / "node_modules").symlink_to(modules, target_is_directory=True)
    shutil.copyfile(ROOT / "package.json", fixture / "package.json")
    (tmp_path / "node_modules").symlink_to(modules, target_is_directory=True)
    runner = tmp_path / "probe.mjs"
    shutil.copyfile(ROOT / "tests/runtime/dsh.mjs", runner)
    result = subprocess.run(
        ["node", str(runner), (fixture / ".dsh/plugins/veripower.js").as_uri()],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(
    os.environ.get("VERIPOWER_CLAUDE_TESTS") != "1" or not shutil.which("claude"),
    reason="opt-in Claude Code runtime probe",
)
def test_claude_native_skill_loading_and_background_completion(tmp_path):
    result = subprocess.run(
        [
            "python3",
            str(ROOT / "tests/runtime/claude.py"),
            "claude",
            str(ROOT),
            str(tmp_path / "workspace"),
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
