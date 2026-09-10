#!/usr/bin/env python3
"""Codex lifecycle adapter; reads one native hook event from stdin."""

import hashlib
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from setup import ROOT, codex_home, reason, rules_text

sys.path.insert(0, str(ROOT / "hooks"))
from loop_after_task_dispatch import REMINDER

GATED = {"pin", "reopen", "signoff"}
INVOCATION = re.compile(r"kernel\.py[\"']?\s+[\"']?(pin|reopen|signoff)\b[\"']?")
DISPATCH = re.compile(r"kernel\.py[\"']?\s+dispatch\b")


def context(event: str, text: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def deny(message: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }


def setup_command() -> str:
    return shlex.join(["python3", str(ROOT / "codex/setup.py")])


def rules_ready() -> bool:
    try:
        return (codex_home() / "rules/veripower.rules").read_text() == rules_text()
    except OSError:
        return False


def session_file(event: dict[str, Any]) -> Path:
    # This is adapter readiness, never pipeline state. Subagent hook events carry
    # their parent's session_id, so the same startup check protects both.
    session = event["session_id"]
    if not isinstance(session, str) or not session:
        raise ValueError("missing session_id")
    digest = hashlib.sha256(session.encode()).hexdigest()
    return Path(os.environ["PLUGIN_DATA"]) / "codex-sessions" / f"{digest}.json"


def start(event: dict[str, Any]) -> dict[str, Any]:
    kind = event["hook_event_name"]
    if kind == "SessionStart":
        state = session_file(event)
        # A compact/resume cannot arm a session that loaded without the rules.
        if event.get("source") == "startup":
            state.parent.mkdir(parents=True, exist_ok=True)
            state.write_text(json.dumps({"root": str(ROOT), "ready": rules_ready()}))
    setup = (
        "Native approval rules match this install. Start with codex --profile veripower."
        if ready_at_start(event)
        else "Judgment commands are blocked in this session. In a terminal run "
        f"{setup_command()}, then start a NEW session: codex --profile veripower."
    )
    text = (ROOT / "codex/instructions.md").read_text()
    return context(kind, text.replace("@ROOT@", str(ROOT)).replace("@SETUP@", setup))


def ready_at_start(event: dict[str, Any]) -> bool:
    try:
        state = json.loads(session_file(event).read_text())
        return state == {"root": str(ROOT), "ready": True} and rules_ready()
    except (OSError, ValueError, KeyError):
        return False


def has_judgment(command: str) -> bool:
    # Catch quoted verbs and escaped path characters as shell tokens, and retain
    # the textual scan for invocations nested inside a shell wrapper's argument.
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = []
    for i, token in enumerate(tokens[:-1]):
        if Path(token).name == "kernel.py" and tokens[i + 1] in GATED:
            if i + 2 == len(tokens) or tokens[i + 2] not in ("--help", "-h"):
                return True
    command = command.replace("\\\n", "")
    for match in INVOCATION.finditer(command):
        tail = command[match.end() :].split(maxsplit=1)
        if not tail or tail[0] not in ("--help", "-h"):
            return True
    return False


def pre_tool(event: dict[str, Any]) -> dict[str, Any] | None:
    command = event["tool_input"]["command"]
    if not isinstance(command, str):
        raise ValueError("missing shell command")
    if not has_judgment(command):
        return None
    if not ready_at_start(event):
        return deny(
            "VeriPower's native approval rules were not ready when this session "
            f"started. Run {setup_command()} in a terminal and start a new "
            "session with codex --profile veripower. Do not retry via another tool."
        )
    if event.get("permission_mode") != "default":
        return deny(
            "VeriPower judgment commands require human approval. Start a new "
            "session with codex --profile veripower; permission bypass and "
            "non-interactive approval modes cannot sign an oracle."
        )
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    argv = list(lexer)
    # Rewriting only a single literal invocation makes the displayed command,
    # native policy match and executed argv agree. Reject shells/wrappers instead
    # of pretending to parse their language or silently removing side effects.
    if (
        len(argv) < 3
        or not re.fullmatch(r"python(?:3(?:\.\d+)?)?", Path(argv[0]).name)
        or Path(argv[1]).name != "kernel.py"
        or argv[2] not in GATED
        or any(token and set(token) <= set(";&|<>()") for token in argv)
        or any(char in command for char in ("$", "`", "\n"))
    ):
        return deny(
            "Run this VeriPower judgment as one plain command with literal "
            f"arguments: python3 {ROOT}/framework/scripts/kernel.py VERB ... . "
            "Shell wrappers, variables and compound commands cannot be approved here."
        )
    kernel = Path(argv[1])
    if not kernel.is_absolute():
        kernel = Path(event["cwd"]) / kernel
    if kernel.resolve() != ROOT / "framework/scripts/kernel.py":
        return deny(
            "This judgment does not address the kernel of this VeriPower install."
        )
    canonical = shlex.join(["python3", str(kernel.resolve()), *argv[2:]])
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": canonical},
            "additionalContext": reason(argv[2]),
        }
    }


def post_tool(event: dict[str, Any]) -> dict[str, Any] | None:
    if not DISPATCH.search(event["tool_input"]["command"]):
        return None
    # Codex 0.153.4 normalizes Bash/unified-exec hook output to a plain stdout
    # string (including when write_stdin delivers completion), unlike CC's dict.
    response = event.get("tool_response")
    if not isinstance(response, str):
        return None
    try:
        out = json.loads(response)
    except ValueError:
        return None
    if not isinstance(out, dict) or out.get("execution") != "task":
        return None
    if not isinstance(out.get("rule"), str) or not isinstance(out.get("run"), int):
        return None
    return context("PostToolUse", REMINDER.format(rule=out["rule"], run=out["run"]))


def main() -> None:
    parser_kind = sys.argv[1] if len(sys.argv) == 2 else ""
    try:
        event = json.load(sys.stdin)
        if parser_kind == "start":
            out = start(event)
        elif parser_kind == "pre":
            out = pre_tool(event)
        elif parser_kind == "post":
            out = post_tool(event)
        else:
            raise ValueError("expected start, pre or post")
    except Exception as exc:
        # A broken pre-hook must block, not emit Codex's unsupported ask value.
        # Post-hook failure only costs a reminder: its command has already run.
        if parser_kind == "pre":
            out = deny(f"VeriPower approval adapter could not inspect this call: {exc}")
        else:
            print(f"veripower-codex: {exc}", file=sys.stderr)
            sys.exit(1)
    if out is not None:
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
    sys.exit(0)
