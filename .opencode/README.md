# VeriPower on opencode

The adapter loads the shared `framework/` and `skills/` through opencode's plugin
API, maps skill and task calls to native tools, and installs approval prompts and
a post-dispatch reminder.

## Install

The integration below is verified on opencode 1.18.30.

Add VeriPower to `~/.config/opencode/opencode.json`, or a project's
`opencode.json`:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git"] }
```

On opencode 1.18.30, background subagents require the following launch flag:

```bash
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true \
OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072 opencode
```

Set the output-token value to your selected model's declared output limit;
`131072` is the example used here. The second flag lifts opencode 1.18.30's
32,000-token completion ceiling for models that support longer output.

For a working copy, launch opencode from the checkout with the same environment
flags. It discovers `.opencode/plugins/veripower.js` as a project plugin. Choose
either the installed package or the project plugin for a session: opencode loads
local and package plugins separately. See opencode's
[plugin loading guide](https://opencode.ai/docs/plugins/).

Ask opencode to list the VeriPower skills, then run `brainstorm` and `design-flow`.
Python and EDA prerequisites are in the [user manual](../docs/USER-MANUAL.md).

## Runtime behavior

The adapter registers its installed `skills/` directory through
`config.skills.paths`. The main agent and its subagents discover the same skills
under bare names, such as `design-flow`.

[plugins/veripower.js](plugins/veripower.js) supplies each session with the
installed root and tool translations: `Skill` becomes `skill`, and background
`Task` becomes `task` with `background: true`. Child prompts use the same bare
skill names and installed paths.

The adapter adds `ask` permission rules for Bash commands matching `kernel.py`
with `pin`, `reopen` or `signoff`, including agent-specific permission tables.
It also allows access to its installation directory. After a task dispatch, a
reminder stays in the model's context until the next kernel call. Stage routing
and results remain the shared kernel's responsibility.

## Removal

Remove the plugin entry from `opencode.json`, or remove the project plugin if
installed locally. Start a new session after changing the plugin or its configuration.

## Check the integration

From a checkout:

```bash
node --check .opencode/plugins/veripower.js
python -m pytest tests/unit/ tests/contracts/
```

The first command checks adapter syntax; the Python suite checks the shared
flow. To check the host integration, use an opencode session with the launch
flags above and confirm skill discovery, background task completion and approval
prompts. See [testing](../tests/README.md) for experiment scope.
