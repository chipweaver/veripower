# VeriPower on DeepSeek Harness

VeriPower installs as a DeepSeek Harness profile layer. The adapter registers
the shared skills through the native provider.

## Install

Validated with DeepSeek Harness 0.2.1-rc.2. Install VeriPower into the profile you run:

```bash
dsh plugin --profile web add "veripower@git+https://github.com/chipweaver/veripower.git"
dsh web
```

For a working copy:

```bash
dsh plugin --profile web add /path/to/veripower
dsh web
```

Use `web` for interactive design work. For SDK sessions, see the
[native SDK guide](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/sdk/server/README.md).

Ask the agent to list the VeriPower skills, then run `brainstorm` and
`design-flow`. Python and EDA prerequisites are in the
[user manual](../docs/USER-MANUAL.md). DeepSeek Harness's
[bundle guide](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/publish.md)
explains profile installation and layer ordering.

## Runtime behavior

The [adapter](plugins/veripower.js) registers the installed skills, supplies native
tool mappings and adds scheduling context after background dispatch. Skill loading,
subagents, completion notifications and permissions use DSH's native mechanisms.

## Update or remove

Web and Desktop provide native plugin management for updates, removal and enablement.

To update:

```bash
dsh plugin --profile web update veripower
```

To remove:

```bash
dsh plugin --profile web remove veripower
```

Hot reload applies changes to the running profile. Follow the host's restart prompt;
restart profiles without hot reload after changes.

Collect active stage runs before uninstalling. Removal can delete the CLI files
that an executor or its parent still needs. Restore the bundle and resume the
session before collecting work interrupted by removal.

To disable the adapter through a profile's `cordis.patch.yml`, add:

```yaml
- id: veripower-dsh
  disabled: true
```

Remove that patch entry to re-enable it.

## Check the integration

```bash
dsh --profile web --dump-config
```

The composed configuration should include `veripower-dsh`. In a running session,
check skill loading, background completion and host permissions. After uninstalling,
a new session should expose neither VeriPower skills nor its tool mapping.

From a VeriPower checkout, `node --check .dsh/plugins/veripower.js` checks adapter
syntax. Shared tests and the distinction between runtime, model and EDA checks
are described in [testing](../tests/README.md).
