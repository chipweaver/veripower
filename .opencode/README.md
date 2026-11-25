# VeriPower on OpenCode 1.19.0

This branch adapts the current VeriPower skills and framework to OpenCode 1.19.0.
The adapter uses native skill discovery, independent background tasks, completion
notifications and host permissions.

## Install

This adapter is on the `opencode-v1` branch; the main branch's OpenCode adapter
targets v2. Use one of the following installation sources.

For a local installation, use a checkout or source archive of `opencode-v1`.
After the branch is published upstream, a source checkout can be obtained with:

```bash
git clone --branch opencode-v1 --single-branch https://github.com/chipweaver/veripower.git veripower-opencode-v1
```

Add the checkout's absolute root to `~/.config/opencode/opencode.json(c)`, or a
project's `opencode.json(c)`:

```json
{ "plugin": ["/absolute/path/to/veripower"] }
```

Once `opencode-v1` is published in the upstream repository, OpenCode can install
the package directly from Git:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git#opencode-v1"] }
```

Merge the selected entry into your existing configuration, preserving other
plugins and settings. If switching from the main/v2 VeriPower installation,
replace its entry with the v1 source. Use the v1 `plugin` configuration shown
above.

When launching OpenCode inside this checkout for development, it automatically
discovers `.opencode/plugins/veripower.js`. Choose either project discovery or
an explicitly configured installation for that session.

The stage scripts need Python 3.10 or later and the packages in
[requirements.txt](../requirements.txt), installed in the Python environment
available to OpenCode's commands. See the [User Guide](../docs/USER-MANUAL.md#1-prepare-the-environment)
for dependency installation. Load your tools, license and library environment
before starting OpenCode; setup is covered in the [EDA environment guide](../docs/eda-env.md).

From your design workspace, launch OpenCode with native background subagents enabled:

```bash
cd /absolute/path/to/design-workspace
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true opencode
```

Start a fresh session and ask:

> List the available VeriPower skills and their installation paths.

Expect bare names such as `brainstorm`, `design-flow`, `specification` and
`rtl-design`, with paths under the selected installation.

## Use

Replace `{module_dir}` below with the absolute path of the module workspace,
which holds its original requirements, generated artifacts and run history.

To check tools and licenses, use a separate session:

> Run the env-precheck skill for all stages of the VeriPower flow.

Put requirements in `{module_dir}/intent/brainstorm.md` and copy referenced
materials into `intent/`. If requirements need discussion, use another session:

> Run the brainstorm skill for {module_dir}.

Review the requirements, then start a fresh session with VeriPower enabled:

> Run the design-flow skill for {module_dir}.

Stages publish their results under the module's `Design/` and `Verification/`
directories. To resume after an interruption, ask:

> Continue the design-flow for {module_dir}. Check outstanding runs and reconcile executor completion before continuing.

The [User Guide](../docs/USER-MANUAL.md) covers task authorization, progress,
reviewing results and revising requirements.

## Runtime behavior

The package exposes OpenCode 1's `{ id, server }` entrypoint. The adapter registers
its installed `skills/` directory through `config.skills.paths`. Parent and child
sessions load bare skill names, such as `synthesis`, through `skill({ name: X })`.

The system transform supplies installed paths and native tool mappings to each
session. `task` with `subagent_type: "general"` and `background: true` starts an
independent executor; OpenCode notifies its parent when it finishes. Commands use
`bash`. The shared flow coordinates dispatch and collection, including
`decide --wake RULE:RUN` after executor exit.

The same system hook adds scheduling reminders when it recognizes a kernel dispatch
in that session's native bash history. A reminder survives executor launch and ends
at the next recognized kernel call. This requires no adapter state across restarts
and leaves stored messages unchanged. Native execution permissions and command text
are unchanged.

## Update, disable or remove

Update a local checkout at its source, then start a fresh session. To switch a
Git package revision, change the configured target to the intended commit or tag
and start a fresh session. Inspect a loaded skill's base directory to verify the
actual installed copy; restarting alone does not establish that a cached package
has been refreshed.

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

## Developer verification

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
