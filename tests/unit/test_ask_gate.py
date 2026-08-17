"""Tests for hooks/ask_judgment_verbs.py — the shipped ask-gate over the three
judgment verbs (ARCHITECTURE.md §2.5).

Two layers, mirroring test_kernel_cli.py: direct import for the classifier, and
a subprocess round-trip for the PreToolUse stdin/stdout contract the harness
actually speaks.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = str(ROOT / "hooks" / "ask_judgment_verbs.py")
sys.path.insert(0, str(ROOT / "hooks"))
import ask_judgment_verbs as gate  # noqa: E402


def _run(payload: str):
    return subprocess.run(
        [sys.executable, SCRIPT],
        input=payload,
        capture_output=True,
        text=True,
    )


def _event(command: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


# --- classifier: the three gated verbs -------------------------------------


def test_pin_is_gated():
    cmd = (
        "python3 framework/scripts/kernel.py pin --module fifo "
        '--rule specification --provenance mhc --reason "reviewed"'
    )
    assert gate.gated_verb(cmd) == "pin"


def test_reopen_is_gated():
    cmd = (
        "python3 framework/scripts/kernel.py reopen --module fifo "
        '--pin-ref specification#1 --reason "spec drifted"'
    )
    assert gate.gated_verb(cmd) == "reopen"


def test_signoff_is_gated():
    cmd = (
        "python3 framework/scripts/kernel.py signoff --module fifo "
        '--provenance mhc --reason "all proofs valid"'
    )
    assert gate.gated_verb(cmd) == "signoff"


def test_install_path_invocation_is_gated():
    """The form the orchestrator emits: `<skill>` resolved against the install."""
    cmd = (
        "python3 /plugins/veripower/skills/design-flow/../../framework/scripts/"
        "kernel.py pin --module fifo --rule simulation --provenance mhc --reason x"
    )
    assert gate.gated_verb(cmd) == "pin"


def test_verb_inside_a_compound_command_is_gated():
    cmd = "cd /w/proj && python3 framework/scripts/kernel.py signoff --module fifo"
    assert gate.gated_verb(cmd) == "signoff"


# --- classifier: what must NOT be gated -------------------------------------


def test_non_judgment_verb_is_not_gated():
    assert (
        gate.gated_verb("python3 framework/scripts/kernel.py decide --module fifo")
        is None
    )


def test_help_is_not_gated():
    assert gate.gated_verb("python3 framework/scripts/kernel.py pin --help") is None


def test_gated_word_as_an_argument_is_not_gated():
    """`pin` must be the verb — the token right after kernel.py — not any mention."""
    assert (
        gate.gated_verb("python3 framework/scripts/kernel.py status --module pin")
        is None
    )
    assert gate.gated_verb("grep -n signoff framework/scripts/kernel.py") is None


def test_unrelated_command_is_not_gated():
    assert gate.gated_verb("pytest -q") is None


# --- PreToolUse contract -----------------------------------------------------


def test_gated_command_asks():
    r = _run(_event("python3 framework/scripts/kernel.py pin --module fifo"))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "ask"
    assert "pin" in out["permissionDecisionReason"]


def test_ungated_command_defers_silently():
    r = _run(_event("python3 framework/scripts/kernel.py status --module fifo"))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_unparseable_input_asks():
    """Fail-ask, not fail-open: a broken gate must not silently disappear."""
    r = _run("not json at all")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask"
