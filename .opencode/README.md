# VeriPower on OpenCode 1.19.0

Use the `opencode-v1` branch. The main branch's OpenCode adapter targets v2.
Stage scripts require Python 3.10+ and [requirements.txt](../requirements.txt) in
the environment used to launch OpenCode. Prepare tools, licenses and libraries
with the [EDA environment guide](../docs/eda-env.md).

## Install

Install the v1 branch through OpenCode's native CLI:

```bash
opencode plugin --global "veripower@git+https://github.com/chipweaver/veripower.git#opencode-v1"
```

For a local checkout:

```bash
git clone --branch opencode-v1 --single-branch https://github.com/chipweaver/veripower.git veripower-opencode-v1
opencode plugin --global /absolute/path/to/veripower-opencode-v1
```

Use the checkout's absolute path in the second command. `--global` installs into
OpenCode's global configuration; omit it for the current project's configuration.
OpenCode 1.19.0 uses `plugin <module>`, rather than v2's `plugin add`.
Add `--force` when replacing an existing VeriPower entry with a different target.

You can also add the target directly to the `plugin` array in
`~/.config/opencode/opencode.json(c)` or a project `opencode.json(c)`:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git#opencode-v1"] }
```

For a local installation, use the absolute checkout path as the entry instead.
Choose one installation for the session. Running OpenCode inside the checkout
also discovers `.opencode/plugins/veripower.js` automatically.

## Use

Load your Python and EDA environment, then start OpenCode from the design workspace
with background subagents enabled:

```bash
cd /absolute/path/to/design-workspace
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true opencode
```

Ask the agent to list VeriPower skills and their installation paths. They use
bare names such as `brainstorm`, `design-flow` and `synthesis`.

In a separate session, check the execution environment:

> Run the env-precheck skill for all stages of the VeriPower flow.

Put reviewed requirements in `{module_dir}/intent/brainstorm.md` and references
in `intent/`. Here `{module_dir}` is the module workspace's absolute path. If
requirements need discussion, first run `brainstorm` in a separate session.
Then start a fresh session and ask:

> Run the design-flow skill for {module_dir}.

Results appear under `Design/` and `Verification/`. To resume, ask:

> Continue the design-flow for {module_dir}.

See the [User Guide](../docs/USER-MANUAL.md) for Python dependency installation,
task preparation, reviewing results and revising requirements.

## Runtime

The adapter registers the installed skills and supplies native tool mappings to
parent and child sessions: `skill` loads a bare name, `task` starts an independent
background executor, and `bash` runs commands. OpenCode delivers normal completion
notifications. After a native background task starts, the adapter adds a reminder
for the VeriPower orchestrator to query the next ready work. Shared design-flow
and kernel own scheduling and collection; native permissions remain unchanged.

## Update or remove

Update a local checkout at its source. OpenCode caches Git targets; for a Git
package update, select a new commit or tag in the configured target. After changing
the source or plugin configuration, restart OpenCode and check a fresh session.
A skill's base directory identifies the loaded copy.

Remove the `plugin` entry to disable or uninstall an explicit installation. For
project discovery, remove the adapter file. Check a fresh session: VeriPower skills
should be absent. Cached files can remain.

OpenCode 1.19.0 does not send the normal completion notification when a child is
explicitly cancelled. Confirm its exit through the host, then resume the parent
to collect the interrupted run.

## Developer verification

```bash
npm ci
node --check .opencode/plugins/veripower.js
python -m pytest tests/unit/ tests/contracts/
VERIPOWER_OPENCODE_TESTS=1 python -m pytest -q tests/unit/test_platform_runtime.py -k opencode
```

`VERIPOWER_OPENCODE_BIN` selects the OpenCode 1.19.0 executable. Native tests use
packed plugins and scripted model responses. Real-model and EDA evidence is in the
[experiment report](../docs/experiments/opencode-v1-full-flow-2026-11-25.zh.md).
See [testing](../tests/README.md) and the
[requirements anchor](../docs/research/opencode-v1-adaptation.zh.md).
