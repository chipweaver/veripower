# Maintaining platform adapters

Use this map to find the implementation affected by a host change, connect it to the
shared workflow, and select evidence for an adapter update or a new platform.
Installation commands belong in each adapter's guide; test commands and verification
scope are described in [tests/README.md](../tests/README.md).

## Responsibilities

[design-flow](../skills/design-flow/SKILL.md) coordinates work through the kernel's
scheduling and evidence records. Stage skills own their engineering work and closure.
Adapters connect skill loading, context, delegation, commands and completion to the
host's native operations. Execution permissions remain with the host. See the
[architecture](ARCHITECTURE.md) and [framework guide](../framework/README.md).

For background work, distinguish kernel dispatch, native executor launch/exit and result
collection. Reminders reinforce the existing scheduling loop.

## Implementation map

| Platform | Entry and implementation | Guide |
|---|---|---|
| Claude Code | [Manifest](../.claude-plugin/plugin.json); [.claude/hooks.json](../.claude/hooks.json), adapter.py and instructions.md | [Claude Code](../.claude/README.md) |
| Codex | [Manifest](../.codex-plugin/plugin.json); [hooks.json](../.codex-plugin/hooks.json), adapter.py and instructions.md | [Codex](../.codex-plugin/README.md) |
| OpenCode v2 | Main branch: package server export and [server.js](https://github.com/chipweaver/veripower/blob/main/.opencode/plugins/veripower/server.js) | [v2 guide](https://github.com/chipweaver/veripower/blob/main/.opencode/README.md) |
| DSH | [Package bundle/export](../package.json), [profile patch](../.dsh/cordis.patch.yml); [veripower.js](../.dsh/plugins/veripower.js) registers skills, prompt and tool context | [DSH](../.dsh/README.md) |
| OpenCode v1 | [Package server export](../package.json), project discovery; [veripower.js](../.opencode/plugins/veripower.js) registers native skills.paths and system/tool hooks | [OpenCode v1](../.opencode/README.md) |

Compare native operations and their purpose, rather than copying file layouts.

## Follow the changed behavior

| Concern | What to trace |
|---|---|
| Loading and context | Discovery, skill names, installed paths and references in both parent and independent child sessions |
| Delegation and scheduling | Independent context, foreground/background semantics, the actual launch event and reminder visibility |
| Completion and lifetime | What a wait operation establishes; executor and shell-job exit, cancellation, session lifetime and resumption |
| Permissions | Native acceptance and refusal, including child operations; engineering authorization remains in the shared skills |
| Installation lifecycle | Source versus cached copy, version/revision actually loaded, update, disable, removal and reinstallation |

Compare the component's purpose and consumer with the target host's actual API before
changing it. A local tool refusal that the existing workflow can handle is an observation,
not by itself a reason for a new global rule. Development principles are in
[CONTRIBUTING.md](../CONTRIBUTING.md#design-principles).

## Select verification

| Question | Evidence and entry points |
|---|---|
| Does the adapter produce the right data? | [Host context](../tests/unit/test_host_context.py), [reminders](../tests/unit/test_dispatch_context.py), [registration](../tests/unit/test_platform_adapters.py) and relevant unit/contract checks |
| Does the native host execute it correctly? | [Claude/OpenCode/DSH probes](../tests/unit/test_platform_runtime.py), [Codex probes](../tests/unit/test_codex_runtime.py); drivers in [tests/runtime/](../tests/runtime/) |
| Does the agent use it correctly? | Real-model tasks; inspect delivered context and actions such as continued scheduling and collection after exit |
| Does the design workflow integrate? | Real EDA and stage handoffs, repairs, current proofs and closure, using the task's original requirements |
| Does installation or recovery work? | Native lifecycle operations and fresh/resumed sessions; inspect actual loaded files as well as command results |

Select checks for the behavior affected by the change. When a hook changes, verify
that it runs and delivers its context; a successful flow alone cannot establish this.
Editorial changes need document review. Execution guidance needs behavioral checks,
including a real model or EDA run when that behavior is affected. Results from another
platform or major version do not replace checks on the target.

## Updating or adding an adapter

Read the shared skills and compare existing implementations, then check the operations
against the target host and version. Reuse its native capabilities; keep engineering
methods in the shared skills.

Update the platform guide and relevant test entry points. Record the reason, checks and
evidence limits, distinguishing plugin changes, design repairs and host observations.
Keep task and site data in experiment records, out of adapter defaults and acceptance rules.
