# VeriPower on Codex

The Codex adapter reuses the repository's `framework/` and twelve `skills/`.
It supplies native plugin discovery, lifecycle hooks, subagent/tool translations,
and native execution-policy approval rules. Claude Code, opencode and DeepSeek
Harness keep their own adapters.

## Install

Use Codex CLI **0.153.4 or later**, on the machine with Python and the EDA tools.
The tested runtime is 0.153.4 on Linux. Start with the interactive CLI; other Codex
surfaces need the same local runtime, hook trust and human approval capabilities.

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
```

For a working copy, replace the first command's source with `/path/to/veripower`.
The existing `.claude-plugin/marketplace.json` is also a supported Codex marketplace;
Codex loads `.codex-plugin/plugin.json` and its explicit `codex/hooks.json` entry.

The install response prints `installedPath`. Use that **installed directory**, not
another checkout, in this command:

```bash
python3 <installedPath>/codex/setup.py
codex --profile veripower
```

`setup.py` writes only two files under your existing `CODEX_HOME` (by default
`~/.codex`):

- `rules/veripower.rules`: native `prompt` rules for this installation's three
  judgment commands. Their approval text includes the trust-boundary explanation.
- `veripower.config.toml`: a dedicated profile selecting workspace-write,
  on-request approvals, the **human** reviewer, hooks and native subagents.

It preserves the main `config.toml`, model choice and other profiles. Re-running
setup updates its own files; a same-named file without its generated header is
left intact and setup fails with its path. `--codex-home DIR` selects a different
configuration directory when preparing another Codex installation.

In `/hooks`, review and trust **all four** VeriPower hooks. Then start a new
session with `codex --profile veripower`; hooks skipped before trust cannot
retroactively prepare the old session. Ask for the `veripower:brainstorm` or
`veripower:design-flow` skill as usual. Python dependencies and EDA prerequisites
are the same as in the [user manual](../docs/USER-MANUAL.md).

After upgrading/reinstalling the plugin, rerun setup from the new `installedPath`,
review any changed hooks, and start a new session. Rules point at the installed
kernel's absolute path; a cached version change must not silently remove approval.
For development at the same version, remove and add the local plugin through the
Codex CLI to refresh the cache, then rerun setup.

## Runtime behavior

`SessionStart` supplies the installed paths and Codex tool mapping; `SubagentStart`
delivers it independently to children. A stage runs in its designated main thread
or a fresh native subagent according to the kernel's `execution` field. No stage
list or routing algorithm lives in the adapter. Use `fork_context=false` on the
0.153.4 tools; on hosts exposing `fork_turns`, use `"none"`.

A task launch is followed immediately by `kernel.py decide`. On `YIELD`, the
parent reports progress and waits for native subagent completion, then continues
the kernel loop. The same translation applies to main-thread skills awaiting
Level-1 children. A long shell command retains its `exec_command` session and is
polled with `write_stdin` to process exit. This avoids relying on parent turn-end
notifications or letting `codex exec` exit while a child is working. Human gates
still return to the user.

`PostToolUse` recognizes a task dispatch from Codex's plain stdout string and
injects the existing measured loop reminder. It does not fire for help, rejected
dispatches or main-thread dispatches. The command and result are the source of
truth, including when a later unified-exec poll delivers the completed output.

## Human judgments

Use one literal command for each judgment:

```bash
python3 <installedPath>/framework/scripts/kernel.py pin --module /path/to/module --rule specification --provenance YOUR_NAME --reason 'reviewed requirements'
```

The same rule applies to `reopen` and `signoff`. Present the signoff basis before
requesting the latter, as design-flow requires. The pre-hook normalizes a plain
invocation to the exact argv protected by Codex's rules. It refuses wrappers,
compound commands, substitutions, another installation's kernel, missing/changed
rules, and approval-bypass modes. `--help` remains available without approval.

The rule must have been present at session startup. Running setup mid-session,
resuming or compacting that session cannot arm it; start a new session instead.
The small files under `PLUGIN_DATA/codex-sessions/` record that startup check only;
all pipeline state remains in the kernel's event log.

Keep the human reviewer selected. Do not use `--approve-for-me`, `--yolo`,
`--ignore-rules`, disable hooks, or allow-list judgment commands for this flow.
Native hooks and command rules are host guardrails, not a sandbox against arbitrary
Python imports, direct event-log edits or deliberately bypassed host policy. An
approval-requiring action in a non-interactive run must fail rather than manufacture
human endorsement. Run that judgment in an interactive session or your own terminal.

Codex 0.153.4 does **not** implement Claude Code's hook response
`permissionDecision: "ask"`. This adapter returns native `deny` or an argv rewrite;
the actual human prompt comes from Codex's execution policy. Its hook configuration
is separate from `hooks/hooks.json` so other platforms retain their existing behavior.

## Verification

```bash
pytest tests/unit/ tests/contracts/
VERIPOWER_CODEX_TESTS=1 pytest -q tests/unit/test_codex_runtime.py
pre-commit run --all-files
```

The opt-in tests drive the real local Codex app-server with a scripted localhost
Responses endpoint. They use no model/API key or EDA license. They check native
approval acceptance/rejection after an argv rewrite, dispatch feedback reaching the
next model request, and fresh child context plus parent waiting. Hook trust is
bypassed only inside those self-authored test fixtures, never persisted; command
approvals remain active. They establish host behavior, not model compliance or an
end-to-end EDA result. A real design-flow/EDA episode remains a separate acceptance
exercise.

References: [plugin packaging](https://developers.openai.com/plugins/build/plugins),
[hooks](https://learn.chatgpt.com/docs/hooks),
[rules](https://learn.chatgpt.com/docs/agent-configuration/rules),
[subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
