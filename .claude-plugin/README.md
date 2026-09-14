# VeriPower on Claude Code

VeriPower uses Claude Code's native plugin discovery, skills and subagents. The
shared design flow lives in `framework/` and `skills/`; two hooks connect it to
Claude Code's shell execution.

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

[hooks/hooks.json](../hooks/hooks.json) registers two shell hooks:

- `PreToolUse` asks for approval when a Bash command invokes `kernel.py pin`,
  `reopen` or `signoff`. These calls record human judgments.
- `PostToolUse` reminds the parent to query `kernel.py decide` after dispatching
  a task, so it can launch other ready stages or wait for the running work.

The kernel continues to own scheduling, artifact versions and stage results.
The hooks add approval prompts and execution context.

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
python -m pytest -q tests/unit/test_ask_gate.py
```

These check the marketplace manifest and the approval hook's command matching
and stdin/stdout protocol. In a running Claude Code session, check that the
VeriPower skills are listed and that stage dispatch uses background subagents.
See [testing](../tests/README.md) for shared checks and model experiments.
