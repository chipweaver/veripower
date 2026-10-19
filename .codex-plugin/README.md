# VeriPower on Codex

The adapter supplies installed paths and translates the shared skills' tool calls to native
subagents and shell execution. Host permissions remain under the user's control.
The command and lifecycle behavior described here was checked with Codex CLI 0.163.0.

## Install

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
codex --enable hooks --enable multi_agent
```

For a working copy, use `/path/to/veripower` as the marketplace source. Codex installs
a copy in its plugin cache; edits to the source checkout need an installation refresh.

VeriPower uses hooks and native subagents; the launch command explicitly enables
both capabilities. Installation does not automatically trust hooks. In `/hooks`,
review and trust VeriPower's SessionStart and SubagentStart hooks, then start a
new session so its adapter context uses the installed paths. Configure the task's
execution permissions in Codex; hook trust and command permission are separate.

Ask the agent to list VeriPower skills. With reviewed requirements at
`{module_dir}/intent/brainstorm.md`, run `design-flow` for the module's absolute
path. If requirements need discussion, use `brainstorm` in a separate session first.
See the [User Guide](../docs/USER-MANUAL.md) for task preparation and continuation,
and the [EDA environment guide](../docs/eda-env.md) for execution prerequisites.

## Update, disable or remove

Complete or cancel and collect active stage runs before updating or removing the
plugin. Codex removes the previous installation's files, so an active executor's
installed paths can disappear. For an interrupted flow, restore the plugin and
resume the session to reconcile the kernel's outstanding runs.

For a configured Git marketplace, refresh its source and the installed plugin:

```bash
codex plugin marketplace upgrade chipweaver
```

For a local marketplace, update the checkout and refresh the installed copy with:

```bash
codex plugin add veripower@chipweaver --json
```

Check the installed version with `codex plugin list --marketplace chipweaver --json`.
Review any hooks marked new or changed in `/hooks`, then start a fresh session.

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

The [manifest](plugin.json) declares skills and hooks relative to the plugin root.
The [adapter](adapter.py) supplies execution mappings through SessionStart and
SubagentStart. Plugin discovery, hook trust and execution permissions are separate
checks. See the official [plugin packaging](https://developers.openai.com/plugins/build/plugins)
and [hooks](https://learn.chatgpt.com/docs/hooks) documentation for those interfaces.

## Verification

```bash
pytest tests/unit/ tests/contracts/
VERIPOWER_CODEX_TESTS=1 pytest -q tests/unit/test_codex_runtime.py
```

The native tests use Codex App Server and a scripted localhost Responses endpoint. They check
host permission acceptance/rejection, ordinary help/execution without plugin prompts, and fresh
subagent context with parent waiting. The probe loads its own fixture hooks with
marketplace plugin loading disabled; it does not test plugin installation or the
interactive hook-trust flow.

For installation or lifecycle changes, use an isolated Codex configuration to
check the registered source, installed files and version, discovered hooks and
their trust status, and the effects of update, disable and removal. Scripted
runtime checks do not measure model reasoning or hardware quality. See
[testing](../tests/README.md) for verification scope.
