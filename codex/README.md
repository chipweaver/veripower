# VeriPower on Codex

The adapter reuses `framework/` and `skills/`, with native plugin discovery,
human approvals and subagents. Tested with Codex CLI 0.153.4 on Linux.

## Install

```bash
codex plugin marketplace add chipweaver/veripower
codex plugin add veripower@chipweaver --json
```

For a working copy, use `/path/to/veripower` as the marketplace source.
Codex reads the existing marketplace and `.codex-plugin/plugin.json`.
Use the install response's `installedPath`:

```bash
python3 <installedPath>/codex/setup.py
codex --profile veripower
```

In `/hooks`, review and trust VeriPower's two hooks, then start a new session.
Run `brainstorm` or `design-flow`. Python and EDA prerequisites are in the
[user manual](../docs/USER-MANUAL.md).

Use the interactive CLI or an App Server client that handles approvals. In the
0.153.4 experiment, `codex exec` forced `approval_policy=never`, preventing the
container-based EDA launchers from requesting access after a sandbox denial.

Setup adds `rules/veripower.rules` and `veripower.config.toml` under `CODEX_HOME`
(default `~/.codex`). The profile enables hooks, subagents and human approvals
within workspace-write. Your main configuration and model choice are preserved.

After a plugin update, rerun setup from the new `installedPath` and start a new
session so Codex loads the updated rules. For local development, remove and add
the plugin through the CLI to refresh its cached copy.

## Adapter boundary

`SessionStart` and `SubagentStart` supply installed paths and translate shared
skills' tool calls into native spawning, waiting and shell execution. The kernel
and skills continue to own stage routing and the design flow.

Native command rules prompt the human reviewer for `pin`, `reopen` and `signoff`.
They match `python3` with the installed kernel path, including the path spelling
used by `design-flow`. These are command-prefix rules; alternate interpreters or
paths are outside their coverage.

## Verification

```bash
pytest tests/unit/ tests/contracts/
VERIPOWER_CODEX_TESTS=1 pytest -q tests/unit/test_codex_runtime.py
pre-commit run --all-files
```

The opt-in tests use the real local Codex app-server and a scripted localhost
Responses endpoint. They check approval acceptance/rejection and fresh subagent
context with parent waiting, without a model or EDA license.

A 4-bit-counter experiment with gpt-6-astra verified the native background EDA
cycle on 2026-09-10. After VCS compiled the RTL through App Server approval, kernel
dispatched lint-cdc to a fresh child. The child ran SpyGlass, polled its process to
exit 0, and finalized a pass with zero errors, warnings and waivers. The parent
waited, reaped that result, and received `DISPATCH synthesis` from its next decide.
The installed framework, skills and adapter were unchanged during the experiment.
Complete simulation, synthesis, timing, power and final signoff remain unverified.
