"""Codex hook delivery and installation alongside existing user configuration."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "veripower_codex_setup", ROOT / "codex/setup.py"
)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.mark.parametrize("event", ["SessionStart", "SubagentStart"])
def test_hook_delivers_installed_paths(event):
    result = subprocess.run(
        [sys.executable, str(ROOT / "codex/adapter.py")],
        input=json.dumps({"hook_event_name": event}),
        text=True,
        capture_output=True,
        check=True,
    )
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == event
    assert str(ROOT / "framework/scripts/kernel.py") in output["additionalContext"]
    assert "@ROOT@" not in output["additionalContext"]


def test_setup_preserves_foreign_configuration(tmp_path):
    profile = tmp_path / "veripower.config.toml"
    profile.write_text('model = "user-choice"\n')
    with pytest.raises(ValueError, match="not managed"):
        setup.install(tmp_path)
    assert profile.read_text() == 'model = "user-choice"\n'
    assert not (tmp_path / "rules/veripower.rules").exists()


def test_setup_is_idempotent_and_keeps_global_config(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('model = "user-choice"\n')
    setup.install(tmp_path)
    setup.install(tmp_path)
    assert config.read_text() == 'model = "user-choice"\n'
    assert (tmp_path / "rules/veripower.rules").read_text() == setup.rules_text()
