"""Codex hook delivery for the installed plugin."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


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
