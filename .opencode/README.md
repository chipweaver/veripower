# VeriPower on opencode

The adapter loads the shared `framework/` and `skills/` through opencode's plugin
API, maps skill and task calls to native tools, and installs approval prompts and
a post-dispatch reminder.

## Install

Add VeriPower to `~/.config/opencode/opencode.json`, or a project's
`opencode.json`:

```json
{ "plugin": ["veripower@git+https://github.com/chipweaver/veripower.git"] }
```

The 1.18.x integration uses background subagents. Launch with:

```bash
OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS=true \
OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072 opencode
```

Set the output-token value to your selected model's declared output limit;
`131072` is the example used here. The second flag lifts opencode 1.18.x's
32,000-token completion ceiling, which can truncate long RTL responses.

For a working copy, launch opencode from the checkout with the same environment
flags. It discovers `.opencode/plugins/veripower.js` as a project plugin. Choose
either the installed package or the project plugin for a session: opencode loads
local and package plugins separately. See opencode's
[plugin loading guide](https://opencode.ai/docs/plugins/).

Ask opencode to list the VeriPower skills, then run `brainstorm` and `design-flow`.
Python and EDA prerequisites are in the [user manual](../docs/USER-MANUAL.md).

## Runtime behavior

The adapter creates `~/.claude/skills/veripower` as a link to the installed
`skills/` directory. This makes the same skills discoverable to the main agent
and its subagents. They register under bare names, such as `design-flow`.

[plugins/veripower.js](plugins/veripower.js) supplies the main agent with the
installed root and tool translations: `Skill` becomes `skill`, and background
`Task` becomes `task` with `background: true`. Child prompts use the same bare
skill names and installed paths.

The adapter adds `ask` permission rules for Bash commands matching `kernel.py`
with `pin`, `reopen` or `signoff`, including agent-specific permission tables.
It also allows access to its installation directory. After a task dispatch, a
reminder stays in the model's context until the next kernel call. Stage routing
and results remain the shared kernel's responsibility.

## Skill discovery and removal

If skills do not appear, inspect `~/.claude/skills/veripower`. The adapter reports
an existing path that points elsewhere and leaves it intact. Resolve that path
conflict, then restart opencode. A dangling link is recreated on startup.

To uninstall, remove the plugin entry from `opencode.json` and remove the skill
symlink created by this adapter. Start a new session after changing the plugin
or its configuration.

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
