# VeriPower on Claude Code

VeriPower uses Claude Code's native plugin discovery, skills and subagents. The
shared design flow lives in `framework/` and `skills/`; Claude Code supplies native execution tools.

## Install

```bash
claude plugin marketplace add chipweaver/veripower
claude plugin install veripower@chipweaver
```

For a working copy:

```bash
claude --plugin-dir /path/to/veripower
```

Start a session with the plugin enabled and ask it to list the VeriPower skills.
Run `veripower:brainstorm` to settle requirements, then `veripower:design-flow`
for the module directory. Python and EDA prerequisites are in the
[user manual](../docs/USER-MANUAL.md).

Claude Code's [plugin guide](https://code.claude.com/docs/en/discover-plugins)
describes installation scopes and plugin management.

## Runtime behavior

The plugin loads the shared skills under the `veripower:` namespace. Stages run
in the main conversation or a background subagent as requested by the shared
orchestrator.

The shared design-flow skill coordinates dispatch, execution and collection.
[The post-dispatch hook](../hooks/hooks.json) supplies scheduling context. Stage skills own
their artifacts; the kernel owns routing and validity. Native execution permissions are unchanged.

## Update or remove

```bash
claude plugin marketplace update chipweaver
claude plugin update veripower@chipweaver
```

Start a new session to load the updated plugin. To remove it:

```bash
claude plugin uninstall veripower@chipweaver
```

## Check the integration

From a checkout:

```bash
claude plugin validate .
python -m pytest -q tests/unit/test_platform_adapters.py
```

These check plugin structure and adapter behavior. In a running session, check skill discovery
and background stage dispatch. See [testing](../tests/README.md) for verification scope.
