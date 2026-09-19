# VeriPower on Codex

The adapter supplies installed paths and translates the shared skills' tool calls to native
subagents and shell execution. Host permissions remain under the user's control.

## Install

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
codex --enable hooks --enable multi_agent
```

For a working copy, use `/path/to/veripower` as the marketplace source. In `/hooks`, review and
trust VeriPower's SessionStart and SubagentStart hooks, then start a new session. Use the host
permission configuration appropriate to the task. VeriPower does not install command approval
rules, create permission profiles or change user policy.
Existing host rules remain effective after a plugin update; review them in the host configuration
when choosing how the task should run.

Run `brainstorm` or `design-flow`. Python and EDA prerequisites are in the
[user manual](../docs/USER-MANUAL.md). Refresh the cached plugin through the Codex plugin CLI
after updating a local checkout, and start a new session.

## Responsibilities

The shared design-flow skill applies the task's actual authorization to engineering decisions.
The kernel records decisions and checks artifact validity. Codex controls whether tool execution
is allowed; a task delegation does not override a host refusal.

## Verification

```bash
pytest tests/unit/ tests/contracts/
VERIPOWER_CODEX_TESTS=1 pytest -q tests/unit/test_codex_runtime.py
```

The native tests use Codex App Server and a scripted localhost Responses endpoint. They check
host permission acceptance/rejection, ordinary help/execution without plugin prompts, and fresh
subagent context with parent waiting. They do not measure model reasoning or hardware quality.
