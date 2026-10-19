# VeriPower on OpenCode

The adapter uses OpenCode 2's native plugin API, skills, background subagents and
completion notifications. The native checks below were exercised with OpenCode 2.0.27.

## Install

Install a package plugin into OpenCode's global configuration through its CLI:

```bash
opencode plugin add git+https://github.com/chipweaver/veripower.git
```

For a working copy, run `npm ci` in the checkout and launch OpenCode there. It
discovers `.opencode/plugins/veripower/server.js`. Use either the package installation
or the project plugin for a session, as described in the
[native plugin guide](https://opencode.ai/v2/docs/plugins).

In a session where the plugin has loaded, ask the agent to list VeriPower skills.
With reviewed requirements at `{module_dir}/intent/brainstorm.md`, run `design-flow`
for the module's absolute path. Use `brainstorm` in a separate session first when
requirements need discussion.

See the [User Guide](../docs/USER-MANUAL.md) for task preparation and continuation,
and the [EDA environment guide](../docs/eda-env.md) for Python, tools, licenses and libraries.

## Runtime behavior

The adapter registers shared skills through `ctx.skill.transform`, with IDs
such as `veripower:synthesis`. Each skill retains its installed file location
and references. Session context supplies native tool mappings to parents and
children: `skill` loads an ID, `subagent` with `background: true` starts an
executor, and `shell` runs commands.

The dispatch reminder is reconstructed from native conversation history. It
survives executor launch and ends at the next kernel action. The adapter leaves
host permissions unchanged; the shared kernel and skills own routing and evidence.

## Update, disable or remove

Use the CLI to check and update installed package plugins:

```bash
opencode plugin check
opencode plugin update git+https://github.com/chipweaver/veripower.git
```

The package target identifies the configured installation. Local directory
plugins are maintained by updating their source files, not through the package
update command.

OpenCode reloads changes under watched configuration directories. Changes to
unwatched local dependencies can require restarting OpenCode. After changing
the adapter, check the active plugin and its skills in a fresh session so the
loaded paths and context correspond to the intended revision. See the native
[reload rules](https://opencode.ai/v2/docs/plugins#reload).

To disable an installed plugin, append `"-veripower"` to the `plugins` array.
Remove that entry to re-enable it. To uninstall the package:

```bash
opencode plugin remove git+https://github.com/chipweaver/veripower.git
```

For a local plugin, remove its configured path or remove it from the discovery
directory, according to how it was loaded. Check a fresh session after disabling
or removing the plugin: VeriPower skills should be absent. Downloaded package
files can remain cached after removal.

## Check

```bash
npm ci
node --check .opencode/plugins/veripower/server.js
python -m pytest tests/unit/ tests/contracts/
```

These check syntax and shared code behavior. Run the opt-in native checks with:

```bash
VERIPOWER_OPENCODE_TESTS=1 python -m pytest -q tests/unit/test_platform_runtime.py -k opencode
```

They pack the plugin, load it in an isolated OpenCode server and use a scripted
localhost provider to check skill loading, fresh child context, background
completion, scheduling reminders and host command refusal. Set
`VERIPOWER_OPENCODE_BIN` to select another OpenCode 2 executable.

For package lifecycle checks, use an isolated installation to inspect the
configured target, active plugin, loaded revision and disable/removal behavior.
See [testing](../tests/README.md) for verification scope.
