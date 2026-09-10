"""Codex hook behavior: native approval normalization and lifecycle feedback."""

import importlib.util
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "codex"))
spec = importlib.util.spec_from_file_location(
    "veripower_codex_adapter", ROOT / "codex/adapter.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    home = tmp_path / "config"
    monkeypatch.setattr(adapter, "codex_home", lambda: home)
    monkeypatch.setenv("PLUGIN_DATA", str(tmp_path / "data"))
    return home


def event(command="", **kwargs):
    return {
        "session_id": "test-session",
        "hook_event_name": "PreToolUse",
        "cwd": str(ROOT),
        "permission_mode": "default",
        "tool_input": {"command": command},
        **kwargs,
    }


def arm(home):
    path = home / "rules/veripower.rules"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(adapter.rules_text())
    adapter.start(event(hook_event_name="SessionStart", source="startup"))


def judgment(verb="pin"):
    return f"python3 {ROOT}/framework/scripts/kernel.py {verb} --module /tmp/m"


def decision(out):
    return out["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize("verb", ["pin", "reopen", "signoff"])
def test_normalizes_to_native_rule_without_losing_arguments(runtime, verb):
    arm(runtime)
    cmd = f"/usr/bin/python3 'skills/design-flow/../../framework/scripts/kernel.py' {verb} --reason 'reviewed: IO & timing'"
    out = adapter.pre_tool(event(cmd))["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert shlex.split(out["updatedInput"]["command"]) == [
        "python3",
        str(ROOT / "framework/scripts/kernel.py"),
        verb,
        "--reason",
        "reviewed: IO & timing",
    ]
    assert out["additionalContext"] == adapter.reason(verb)


def test_installing_rules_mid_session_does_not_arm_it(runtime):
    adapter.start(event(hook_event_name="SessionStart", source="startup"))
    path = runtime / "rules/veripower.rules"
    path.parent.mkdir(parents=True)
    path.write_text(adapter.rules_text())
    assert decision(adapter.pre_tool(event(judgment()))) == "deny"
    adapter.start(event(hook_event_name="SessionStart", source="compact"))
    assert decision(adapter.pre_tool(event(judgment()))) == "deny"
    adapter.start(event(hook_event_name="SessionStart", source="resume"))
    assert decision(adapter.pre_tool(event(judgment()))) == "deny"


def test_changed_rule_blocks_an_already_armed_session(runtime):
    arm(runtime)
    (runtime / "rules/veripower.rules").write_text(
        'prefix_rule(pattern=["python3"], decision="allow")'
    )
    assert decision(adapter.pre_tool(event(judgment()))) == "deny"


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", "plan", None])
def test_noninteractive_or_bypassed_approval_cannot_sign(runtime, mode):
    arm(runtime)
    assert decision(adapter.pre_tool(event(judgment(), permission_mode=mode))) == "deny"


@pytest.mark.parametrize(
    "cmd",
    [
        "python3 kernel.py pin --help; python3 kernel.py signoff --module m",
        "cd /tmp && python3 kernel.py pin --module m",
        "python3 kernel.py pin --module $MODULE",
        "bash -c 'python3 kernel.py signoff --module m'",
        "python3 kernel.py signoff --module m > log",
    ],
)
def test_cannot_hide_a_judgment_inside_shell_syntax(runtime, cmd):
    arm(runtime)
    assert decision(adapter.pre_tool(event(cmd))) == "deny"


@pytest.mark.parametrize(
    "cmd",
    [
        "python3 kernel.py pin --help",
        "python3 kernel.py signoff -h",
        "python3 kernel.py status --module pin",
        "python3 kernel.py dispatch --module m --rule lint-cdc",
        "pytest -q",
    ],
)
def test_ordinary_calls_do_not_need_adapter_setup(runtime, cmd):
    assert adapter.pre_tool(event(cmd)) is None


def test_another_install_cannot_use_this_installs_rules(runtime):
    arm(runtime)
    assert (
        decision(
            adapter.pre_tool(
                event("python3 /other/framework/scripts/kernel.py pin --module m")
            )
        )
        == "deny"
    )


def test_subagent_receives_mapping_without_rearming_session(runtime):
    arm(runtime)
    out = adapter.start(event(hook_event_name="SubagentStart"))["hookSpecificOutput"]
    assert out["hookEventName"] == "SubagentStart"
    assert str(ROOT / "framework/scripts/kernel.py") in out["additionalContext"]
    assert "@ROOT@" not in out["additionalContext"]
    assert decision(adapter.pre_tool(event(judgment()))) == "allow"


def test_native_plain_stdout_delivers_measured_reminder():
    out = adapter.post_tool(
        event(
            "python3 kernel.py dispatch --module m --rule lint-cdc",
            tool_response=json.dumps(
                {"execution": "task", "rule": "lint-cdc", "run": 4}
            ),
        )
    )
    assert out == adapter.context(
        "PostToolUse", adapter.REMINDER.format(rule="lint-cdc", run=4)
    )


@pytest.mark.parametrize(
    "response",
    [
        "usage: kernel.py dispatch ...",
        "",
        "Traceback: missing module",
        '{"ok": false}',
        '{"execution": "main-thread"}',
        "[]",
        {"stdout": '{"execution": "task"}'},
    ],
)
def test_non_dispatch_results_do_not_emit_a_reminder(response):
    assert (
        adapter.post_tool(event("python3 kernel.py dispatch", tool_response=response))
        is None
    )


def test_broken_pre_hook_blocks_instead_of_returning_unsupported_ask():
    result = subprocess.run(
        [sys.executable, str(ROOT / "codex/adapter.py"), "pre"],
        input="not json",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert decision(json.loads(result.stdout)) == "deny"


def test_setup_preserves_foreign_configuration(runtime):
    from setup import install

    runtime.mkdir()
    profile = runtime / "veripower.config.toml"
    profile.write_text('model = "user-choice"\n')
    with pytest.raises(ValueError, match="not managed"):
        install(runtime)
    assert profile.read_text() == 'model = "user-choice"\n'
    assert not (runtime / "rules/veripower.rules").exists()


def test_setup_is_idempotent_and_keeps_global_config(runtime):
    from setup import install

    runtime.mkdir()
    config = runtime / "config.toml"
    config.write_text('model = "user-choice"\n')
    install(runtime)
    install(runtime)
    assert config.read_text() == 'model = "user-choice"\n'
    assert (runtime / "rules/veripower.rules").read_text() == adapter.rules_text()


@pytest.mark.parametrize(
    "command",
    [
        "python3 framework/scripts/kernel.py 'pin' --module m",
        'python3 framework/scripts/kernel.py "signoff" --module m',
        "python3 framework/scripts/kernel\\.py reopen --module m",
        "python3 framework/scripts/kernel.py \\\n pin --module m",
    ],
)
def test_quoting_cannot_skip_the_startup_gate(runtime, command):
    assert decision(adapter.pre_tool(event(command))) == "deny"
