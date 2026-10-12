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
[user manual](../docs/USER-MANUAL.md).

## Update, disable or remove

Complete or cancel and collect active stage runs before updating or removing the
plugin. Codex removes the previous installation's files, so an active executor's
installed paths can disappear. For an interrupted flow, restore the plugin and
resume the session to reconcile the kernel's outstanding runs.

For the Git marketplace:

```bash
codex plugin marketplace upgrade chipweaver
codex plugin add veripower@chipweaver --json
```

For a local marketplace, update the checkout and run the same `plugin add` command
to refresh the installed copy. Start a new session. Unchanged hook definitions retain
their trust; changed definitions require review in `/hooks`.

To disable the plugin, set `enabled = false` under
`[plugins."veripower@chipweaver"]` in Codex configuration. Set it to `true` to re-enable.
To uninstall:

```bash
codex plugin remove veripower@chipweaver --json
```

A new session should contain neither VeriPower skills nor its hooks. Removing the
marketplace itself is a separate `codex plugin marketplace remove chipweaver` operation.

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
