# VeriPower on OpenCode

The adapter uses OpenCode's native plugin API, skills, background subagents and
completion notifications. It targets OpenCode 2.0.26; OpenCode 1 is no longer supported.

## Install

Install through the native plugin CLI:

```bash
opencode plugin add git+https://github.com/chipweaver/veripower.git
```

For a working copy, run `npm ci` in the checkout and launch OpenCode there. It
discovers `.opencode/plugins/veripower/server.js`. Use either the package installation
or the project plugin for a session, as described in the
[native plugin guide](https://opencode.ai/v2/docs/plugins).

Ask the agent to list VeriPower skills, then run `brainstorm` and `design-flow`.
Python and EDA prerequisites are in the [user manual](../docs/USER-MANUAL.md).

## Runtime behavior

The adapter registers shared skills through `ctx.skill.transform`, with IDs
such as `veripower:synthesis`. Each skill retains its installed file location
and references. Session context supplies native tool mappings to parents and
children: `skill` loads an ID, `subagent` with `background: true` starts an
executor, and `shell` runs commands. OpenCode 2 needs no experimental background flag.

The dispatch reminder is reconstructed from native conversation history. It
survives executor launch and ends at the next kernel action. The adapter leaves
host permissions unchanged; the shared kernel and skills own routing and evidence.

## Update, disable or remove

With the plugin active in a running OpenCode session:

```bash
opencode plugin check
opencode plugin update git+https://github.com/chipweaver/veripower.git
```

Start a new session after updating. A working copy loads its local changes after
restarting OpenCode.

To disable an installed plugin, append `"-veripower"` to the `plugins` array.
Remove that entry to re-enable it. To uninstall the package:

```bash
opencode plugin remove git+https://github.com/chipweaver/veripower.git
```

For a local project plugin, remove its directory. Start a new session and check
that VeriPower skills are absent. OpenCode may retain downloaded package files.

## Check

```bash
npm ci
node --check .opencode/plugins/veripower/server.js
python -m pytest tests/unit/ tests/contracts/
```

These check syntax and adapter behavior. Native checks must also establish skill
loading in parent and child sessions, background completion and host permissions.
See [testing](../tests/README.md) for the difference between runtime, model and EDA checks.
Lifecycle checks cover installation, update, disable, removal and reinstallation;
inspect fresh registrations and actual installed revisions.
