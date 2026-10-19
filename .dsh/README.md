# VeriPower on DeepSeek Harness

VeriPower installs as a DeepSeek Harness profile layer. The adapter registers
the shared skills through the native provider.

## Install

Validated with DeepSeek Harness 0.2.1-rc.2. Installation belongs to a profile;
use the same profile when installing and running VeriPower. The examples use `web`:

```bash
dsh plugin --profile web add "veripower@git+https://github.com/chipweaver/veripower.git"
dsh web
```

For a working copy:

```bash
dsh plugin --profile web add /path/to/veripower
dsh web
```

`web` provides an interactive entry point. For SDK sessions, see the
[native SDK guide](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/packages/sdk/server/README.md).

In the chosen profile, ask the agent to list VeriPower skills. With reviewed
requirements at `{module_dir}/intent/brainstorm.md`, run `design-flow` for the
module's absolute path. If requirements need discussion, use `brainstorm` in a
separate session first. See the [User Guide](../docs/USER-MANUAL.md) for the task
workflow and the [EDA environment guide](../docs/eda-env.md) for execution prerequisites.

The [bundle guide](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/docs/user/develop/basic/publish.md)
and [CLI reference](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/apps/cli/README.md)
describe profile installation and layer ordering for this release.

## Runtime behavior

The [adapter](plugins/veripower.js) registers the installed skills, supplies native
tool mappings and adds scheduling context after background dispatch. Skill loading,
subagents, completion notifications and permissions use DSH's native mechanisms.

## Update or remove

Web and Desktop provide native plugin management for updates, removal and
enablement. The CLI commands below manage the `web` profile. Desktop uses its
own installation runtime; the npm CLI's profile commands do not manage it.

To update:

```bash
dsh plugin --profile web update veripower
```

To remove:

```bash
dsh plugin --profile web remove veripower
```

Profiles with hot reload enabled apply watched configuration changes while
running. Follow the host's restart prompt; restart profiles without hot reload
after changes.

Collect active stage runs before uninstalling. Removal can delete the CLI files
that an executor or its parent still needs. Restore the bundle and resume the
session before collecting work interrupted by removal.

To disable the adapter, add this entry to the profile's `cordis.patch.yml` list:

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

From a VeriPower checkout, `node --check .dsh/plugins/veripower.js` checks syntax.
The native component probe uses the installed DSH packages:

```bash
VERIPOWER_DSH_NODE_MODULES=/path/to/dsh/node_modules \
  python -m pytest -q tests/unit/test_platform_runtime.py -k dsh
```

Use the package directory for the DSH release being checked. This probe verifies
skill registration, scoped prompt assembly, native tool decisions and deferred
context encoding in native components. Check profile installation, reload and
background execution through the composed configuration and a running profile.
See [testing](../tests/README.md) for the distinction between runtime, model and
EDA evidence.
