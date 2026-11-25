# VeriPower on OpenCode 1

This branch adapts the current VeriPower skills and framework to OpenCode 1.19.0.
The adapter uses native skill discovery, independent background tasks, completion
notifications and host permissions.

## Install

Use a checkout of the `opencode-v1` branch. Add its absolute root to
`~/.config/opencode/opencode.json`, or a project's `opencode.json`:

```json
{ "plugin": ["/absolute/path/to/veripower"] }
```

Launch OpenCode with its native background subagent capability enabled:

```bash
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true opencode
```

For development in this checkout, OpenCode automatically discovers
`.opencode/plugins/veripower.js`. Use either project discovery or an explicitly
configured installation for a session.

Once this branch is published, a package installation can select the same source:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git#opencode-v1"] }
```

In a fresh session, ask the agent to list the VeriPower skills. With reviewed
requirements at `{module_dir}/intent/brainstorm.md`, run `design-flow` for the
module's absolute path. Use `brainstorm` first when requirements need discussion.

See the [User Guide](../docs/USER-MANUAL.md) for task preparation and continuation,
and the [EDA environment guide](../docs/eda-env.md) for Python, tools, licenses and libraries.

## Runtime behavior

The package exposes OpenCode 1's `{ id, server }` entrypoint. The adapter registers
its installed `skills/` directory through `config.skills.paths`. Parent and child
sessions load bare skill names, such as `synthesis`, through `skill({ name: X })`.

The system transform supplies installed paths and native tool mappings to each
session. `task` with `subagent_type: "general"` and `background: true` starts an
independent executor; OpenCode notifies its parent when it finishes. Commands use
`bash`. The shared flow coordinates dispatch and collection, including
`decide --wake RULE:RUN` after executor exit.

The same system hook reads that session's native history to reconstruct dispatch
reminders. A reminder survives executor launch and ends at the next kernel action.
This requires no adapter state across restarts and leaves stored messages unchanged.
Native execution permissions and command text are unchanged.

## Update, disable or remove

Update a local checkout at its source, then start a fresh session. For a package
installation, select the intended Git ref in the `plugin` configuration and start
a fresh session to load it. Inspect a loaded skill's base directory to verify the
actual installed copy.

To disable or remove an explicitly configured installation, remove its `plugin`
entry. For project discovery, remove the adapter file from the discovery directory.
Start a fresh session and verify that VeriPower skills and its tool mapping are
absent. Cached package files may remain after configuration removal.

If work was interrupted, use the restored plugin and the shared design-flow to
check outstanding runs and reconcile executor completion before collecting results.
The kernel records stage work; OpenCode owns live executor state. In 1.19.0,
explicitly cancelling a child session does not send its parent the normal completion
notification. Confirm the cancellation through the host and resume the parent to
collect the interrupted run.

## Check

```bash
npm ci
node --check .opencode/plugins/veripower.js
python -m pytest tests/unit/ tests/contracts/
```

The native runtime checks pack and install the plugin in isolated OpenCode 1.19.0
servers, using scripted localhost model responses:

```bash
VERIPOWER_OPENCODE_TESTS=1 python -m pytest -q tests/unit/test_platform_runtime.py -k opencode
```

Set `VERIPOWER_OPENCODE_BIN` to select another executable of that version. The
checks cover installed skills, independent child context, native completion,
scheduling reminders and host command acceptance, denial and rejected approval.
They also check disabled background capability and parent resumption after
host-confirmed cancellation.
Real model and EDA experiments are recorded separately from these scripted checks.
See [testing](../tests/README.md) and the
[adaptation anchor](../docs/research/opencode-v1-adaptation.zh.md). The
[complete counter experiment](../docs/experiments/opencode-v1-full-flow-2026-11-25.zh.md)
records a real model running all eight stages with EDA tools, independent reviews,
background collection and kernel closing/signoff. The
[component report](../docs/experiments/opencode-v1-2026-11-25.zh.md) records runtime,
CLI, recovery and installation lifecycle checks.
