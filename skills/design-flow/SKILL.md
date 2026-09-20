---
name: design-flow
description: Use when progressing IC design through stages, checking module status, or routing rework decisions; not for single-stage execution or artifact authoring.
---

# Design Flow

Coordinate module stages, rework and delivery through
`python3 <skill>/../../framework/scripts/kernel.py`, written `kernel.py` below.
`<skill>` is this skill's directory; `{module}` contains `events.jsonl`,
`intent/brainstorm.md` and the stage trees.

The kernel owns events and scheduling. Stage executors own their workdir artifacts and close
through the stage CLI, whether running in this conversation or in a subagent. While orchestrating,
use the kernel rather than editing events or stage results directly. Inspect source when needed
to understand an operation.

Use `kernel.py status --module {module}` to check current status. Command arguments are available
through `kernel.py <command> --help`.

## Run the work

Run the kernel loop:

```text
loop:
  a = kernel.py decide --module {module} [--wake <rule>:<run>] [--closing]
  execute(a)  # actions below; launching a background executor does not wait for it
  if a.action == DONE: finish
```

For `DISPATCH`, invoke the returned `dispatch_args` through the kernel CLI. The response prepares
the workdir and identifies the executor; it does not start that executor.

| `execution` | Start the work |
|---|---|
| `main-thread` | Invoke the returned skill in this conversation, acting as that stage's executor. |
| `task` | Render [the stage prompt](../../framework/references/prompts/stage-subagent.md.tpl) with the module, rule, skill and workdir from dispatch; launch it with `Task(run_in_background=True, prompt=<rendered>)`. |

After launching a background executor, query `decide` again so other ready work can proceed.
Confirm executor exit through the host before waking or reaping its run; a result file or `YIELD`
does not establish exit. Once it exits, pass `--wake <rule>:<run>` to `decide`, including when it
left no result. Carry out the returned action:

- `REAP`: run `kernel.py reap --module {module} --rule <rule> --run <run>`, then query again.
  Reap uses that run's result; an absent result is handled as an incomplete execution.
- `YIELD`: report the running work and wait for an executor completion before resuming.
- `ESCALATE`: address the reported blocker under the authorization below, then query `decide`
  again. Wait when needed information or a reserved human decision is unavailable.
  `kernel.py diagnose` records a later addition or correction to repair ownership;
  `--supersedes` identifies the diagnosis being replaced.
- `DONE`: deliver the conclusions and complete any acceptance in scope, as described below.

A failed CLI operation remains incomplete until its reported cause is resolved.

## Decisions and authorization

Follow the user's actual authorization. For a reserved decision, present the specific choice,
evidence and unresolved issues, then wait. Within explicit delegation, decide and act in scope.
A refusal remains binding. Host execution permission is separate from decision authorization.
For `diagnose` and `signoff`, `--provenance` identifies the decision maker and authorization;
`--reason` gives the engineering grounds.

For artifact changes, `kernel.py consequences --module {module} --paths <path…>` shows which
valid proofs the change would invalidate.

## Completion and acceptance

Report what the delivered evidence establishes and any remaining limits. Recheck concrete issues
through the responsible stage and existing repair flow. Completion requires separate approval
only when the task reserves that decision.

When the task calls for a recorded acceptance, use `decide --closing` to check the current
conclusions and delivered artifacts. Present the returned basis, follow the authorization above,
and record acceptance with:

```bash
kernel.py signoff --module {module} --provenance "<decision maker and authorization>" \
  --reason "<basis for accepting this delivery>"
```

The record applies to the accepted evidence. New stage conclusions need a new acceptance when
that is in scope; repeating collection of unchanged evidence does not. An acceptance record does
not establish a missing technical fact or resolve a failed check.
