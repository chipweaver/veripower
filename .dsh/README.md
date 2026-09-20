# VeriPower on DeepSeek Harness

VeriPower installs as a DeepSeek Harness profile layer. The adapter registers
the shared skills through the native provider.

## Install

With [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) installed,
add VeriPower to the profile you will run:

```bash
dsh plugin --profile web add "veripower@git+https://github.com/chipweaver/veripower.git"
dsh web
```

For a working copy:

```bash
dsh plugin --profile web add /path/to/veripower
dsh web
```

Use the long-lived `web` profile for the design flow: it keeps the session
available for stage completions and human approval prompts. `headless` is a
one-shot task runner.

Ask the agent to list the VeriPower skills, then run `brainstorm` and
`design-flow`. Python and EDA prerequisites are in the
[user manual](../docs/USER-MANUAL.md). DeepSeek Harness's
[bundle guide](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md)
explains profile installation and layer ordering.

## Runtime behavior

The root [package.json](../package.json) declares the bundle patch at
[cordis.patch.yml](cordis.patch.yml), which loads
[plugins/veripower.js](plugins/veripower.js).

The adapter locates this installation's `skills/` directory and registers it
through an isolated filesystem skill provider. No global skill symlink or
manually configured skill path is needed.

The adapter maps `Skill(veripower:X)` to `skill` with the bare name `X`, and background
`Task` to `subagent` with `run_in_background: true`. These translations are supplied
through the host's system prompt to the parent and child agents.

The adapter supplies post-dispatch scheduling context. The profile supplies execution tools
and permissions. The shared design-flow skill coordinates
execution and collection; the kernel owns stage routing and validity.

## Update or remove

To update:

```bash
dsh plugin --profile web update veripower
```

To remove:

```bash
dsh plugin --profile web remove veripower
```

Restart the profile after either operation. Plugin management forwards to pnpm
in that profile and updates its bundle layers.

## Check the integration

```bash
dsh --profile web --dump-config
```

The composed configuration should include the `veripower-dsh` layer entry. In the
web session, check that skills are available, task completions return to the
parent, and host permissions remain effective.

From a VeriPower checkout, `node --check .dsh/plugins/veripower.js` checks adapter
syntax. Shared tests and the distinction between runtime, model and EDA checks
are described in [testing](../tests/README.md).
