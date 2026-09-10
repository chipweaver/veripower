# Contributing to VeriPower

VeriPower shares its design flow across Claude Code, opencode, DeepSeek Harness and
Codex. Start with the problem and the behavior you want to change. Read the relevant
code and try the current behavior; existing documentation and implementation can both
be wrong and are open to revision.

## Design principles

- Trust the model to reason. Give it the task, evidence and necessary boundaries;
  avoid prescribing every step or accumulating warnings for hypothetical mistakes.
- Keep the solution small. Remove obsolete behavior and its callers together.
  Do not add fallback paths, degraded success, arbitrary retry budgets or compatibility
  layers to preserve a design being replaced.
- Add a field or schema only when an actual consumer needs structured data. Use prose
  for engineering judgment; do not build a parser and validator just to formalize it.
- Keep shared capabilities in `framework/` and `skills/`. Use each platform's native
  facilities in its adapter, and preserve the other platforms' capabilities.
- State guidance once, close to its use. Delete stale instructions instead of adding
  exceptions around them.

## Where changes belong

| Area | Location |
|---|---|
| Stage work, instructions and EDA tools | `skills/<stage>/` |
| Scheduling, event history and artifact provenance | `framework/scripts/` |
| Claude Code integration | `.claude-plugin/`, `hooks/` |
| opencode integration | `.opencode/` |
| DeepSeek Harness integration | `.dsh/` |
| Codex integration | `.codex-plugin/`, `codex/` |

For a stage change, follow its inputs through the skill, scripts and outputs. Keep
commands, callers and result readers consistent. A new stage also needs registration
in [rules.py](framework/scripts/rules.py); dependencies are derived from its inputs.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the current scheduling and provenance model.

Skills may link to references and scripts. They should be usable from an installed
plugin without relying on repository instructions or the author's session memory.
Resolve plugin files from the installed skill location (`<skill>` in shared commands),
not the design workdir. Put platform-specific tool translation in the adapter.

Check the consumer before changing an output. Validate data that code depends on,
and keep EDA pass/fail grounded in the tool results and the engineer's requirements.
Formatting a model's judgment as JSON does not establish its correctness.

## Development and validation

Use Python 3.10 or later:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/unit/ tests/contracts/
pre-commit run --all-files
```

Choose checks that exercise the change. Add regression tests for meaningful code
behavior; do not add tests that merely repeat the implementation or pin prose wording.
Documentation-only edits need review of facts, commands and links. Formatting is owned
by [.pre-commit-config.yaml](.pre-commit-config.yaml), not a separate style checklist.
See [tests/README.md](tests/README.md) for the available tests and commands.

Test platform behavior on the platform being changed: Codex for Codex, Claude Code
for Claude Code, and likewise for the other adapters. For shared changes, select the
affected platform checks and report what was exercised. One platform's result does
not establish another's behavior. The current CI jobs are in
[ci.yml](.github/workflows/ci.yml); they do not run live model or EDA experiments.

Use a model experiment when the uncertainty concerns agent behavior. Give the agent
the materials and tools the task actually needs, without the author's conversation
or answer key. Check its actions and artifacts. A comparison with and without an
instruction can help decide whether to keep it; a baseline failure is not a prerequisite
for a useful regression case. Investigate a failure before adding more instructions.

Distinguish a scripted runtime test, a real model run, an EDA tool run and a complete
flow. Record the platform/model, relevant versions, task, observed outcome and limits
of the evidence in a concise report. If a check cannot run, say why. Keep temporary
workdirs and raw logs out of commits; retain only evidence needed to understand or
reproduce the result. EDA prerequisites are in [docs/eda-env.md](docs/eda-env.md).

## Commits and pull requests

Keep each change coherent and reviewable. Use a short `type: description` title,
such as `fix: ...` or `docs: ...`. Explain the problem, resulting behavior and any
non-obvious decision. Include relevant validation and what remains unverified;
scale the detail to the change. Link an issue when applicable.

Write runtime skill instructions in English. User-facing material may follow the
user's language. Keep prose direct and link to detailed references instead of
copying them into every document.
