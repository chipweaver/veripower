# Agent scenarios

Scenarios exercise agent behavior on a concrete task. Use them when a code test cannot
answer the question under investigation. General validation guidance lives in
[CONTRIBUTING.md](../../CONTRIBUTING.md#development-and-validation).

Run on the platform and model relevant to the change. Provide the task's normal
instructions, references and tools, without the author's conversation or answer key.
Inspect actions and resulting artifacts when testing execution; a stated choice alone
only tests a stated choice.

## Existing Claude runner

[scenario-run.sh](scenario-run.sh) currently invokes `claude -p --model opus`.
It is a Claude-specific runner, not a requirement to use Claude for other platforms.
There is no Codex scenario runner in this directory. Codex experiments should use
Codex; the [native runtime tests](../../codex/README.md#verification) use scripted
responses and do not substitute for model scenarios.

```bash
./tests/scenarios/scenario-run.sh --skill simulation --scenario 01 --mode red
./tests/scenarios/scenario-run.sh --skill simulation --scenario 01 --mode green
```

`red` supplies the scenario without skill guidance. `green` also supplies the skill's
`SKILL.md`. To include a reference used by the task, add
`--extra skills/<skill>/references/<file>.md` in green mode. The mode names do not
prescribe what the model must answer; a model may solve the task without the skill.

The runner uses a temporary workdir and home, links existing Claude credentials, and
configures a tool deny list. `stream_text.py` rejects transcripts that list available
tools or contain tool calls. Inspect isolation results when the CLI changes. This
runner measures responses without tools, not actual file edits, dispatch or EDA work.
Authentication failures, rate limits and isolation failures are not scenario outcomes.

## Scenario files and results

Existing files use frontmatter for the skill, scenario ID, title and type. Templates
are in `templates/`. The runner accepts an ID or a file path and removes the answer-key
sections (`Expected Behavior` and `Anti-Pattern`) before sending the task.

| Type | Output inspected |
|---|---|
| `pressure` | `DECISION: A/B/C`, compared with the scenario's expected choice |
| `missing-info` | `ACTION: PROCEED/BLOCKED`, interpreted against the task |
| `open` | Response reviewed against the expected behavior |

Historical `baseline`, `green`, `activated`, `model` and `provenance` entries describe
past measurements. Revisit their assumptions before using a case as a regression test.
Keep useful cases, including cases a bare model already solves; remove obsolete ones.
Do not manufacture pressure merely to make a baseline fail.

Record the actual platform/model, supplied context, observed behavior and limitations
of a new experiment. Keep the task and useful findings reproducible; temporary runs
and raw transcripts belong outside tracked files (`results/` is ignored).
