# VeriPower on Claude Code

VeriPower uses Claude Code's native plugin discovery, skills and subagents. The
shared design flow lives in `framework/` and `skills/`; Claude Code supplies native execution tools.

## Install

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

The install command uses user scope by default. Use `--scope project` or
`--scope local` when that is the intended scope. Select the matching scope when
enabling, disabling or uninstalling the plugin. See Claude Code's
[plugin guide](https://code.claude.com/docs/en/discover-plugins) for scope and loading rules.

To load a working copy for one session:

```bash
claude --plugin-dir /path/to/veripower
```

Start a fresh session with the plugin enabled and ask it to list the VeriPower
skills. With reviewed requirements at `{module_dir}/intent/brainstorm.md`, run
`veripower:design-flow` for the module's absolute path. If requirements need
discussion, use `veripower:brainstorm` in a separate session first.

Task preparation and continuation are covered in the [User Guide](../docs/USER-MANUAL.md).
Python, EDA tools, licenses and libraries are covered in the
[EDA environment guide](../docs/eda-env.md).

## Runtime behavior

The adapter supplies native tool mappings through SessionStart and SubagentStart.
It loads the shared skills under the `veripower:` namespace. Stages run
in the main conversation or a background subagent as requested by the shared
orchestrator.

The shared design-flow skill coordinates dispatch, execution and collection.
[The adapter hooks](hooks.json) supply scheduling context. Stage skills own
their artifacts; the kernel owns routing and validity. Native execution permissions are unchanged.

## Update or remove

Refresh the marketplace catalog, then update the installed plugin:

```bash
claude plugin marketplace update chipweaver
claude plugin update veripower@chipweaver
```

Claude Code also supports plugin reload operations. A fresh session loads the
updated plugin and runs VeriPower's SessionStart hook with its current installed
paths. For `--plugin-dir`, update the checkout and start a new session with that path.

To remove the user-scope installation:

```bash
claude plugin uninstall veripower@chipweaver
```

Use `claude plugin disable veripower@chipweaver` and
`claude plugin enable veripower@chipweaver` to toggle it without uninstalling. Check a new session after
either operation. Uninstall removes registration; Claude Code may retain cached files.

## Check the integration

From a checkout:

```bash
claude plugin validate . --strict
claude plugin validate .claude-plugin/plugin.json --strict
python -m pytest -q tests/unit/test_host_context.py tests/unit/test_dispatch_context.py
```

These check plugin structure and adapter logic. To exercise the native parent
and child sessions with a scripted localhost Messages endpoint:

```bash
VERIPOWER_CLAUDE_TESTS=1 python -m pytest -q tests/unit/test_platform_runtime.py -k claude
```

This probe loads the checkout through `--plugin-dir` and checks adapter context,
skill loading and background completion. To check installation and lifecycle
behavior, inspect the registered scope, installed version and actual loaded copy
in an isolated installation. See [testing](../tests/README.md) for verification scope.

`hooks.json` configures installed plugin execution. `settings.json`, `CLAUDE.md` and
`hooks/` configure development sessions in this repository; installing the plugin does
not activate those project settings in another workspace.
