---
name: design-flow
description: Use when progressing IC design through stages, checking module status, or routing rework decisions; not for single-stage execution or artifact authoring.
---

# Design Flow

Coordinate stage work through `python3 <skill>/../../framework/scripts/kernel.py`, written
`kernel.py` below. `<skill>` is this skill's directory; `{module}` contains `events.jsonl`,
`intent/brainstorm.md` and the stage trees.

The kernel owns events and scheduling. Stage executors own their workdir artifacts and close
through the stage CLI. An executor may run in this conversation or in a subagent; its stage
responsibilities are the same. While orchestrating, use the kernel rather than editing events
or stage results directly. Inspect source when needed to understand an operation.

## Run the work

Query the next action:

```bash
kernel.py decide --module {module} [--wake <rule>:<run>] [--closing]
```

For `DISPATCH`, invoke the returned `dispatch_args` through the kernel CLI. The response prepares
the workdir and identifies the executor; it does not start that executor.

| `execution` | Start the work |
|---|---|
| `main-thread` | Invoke the returned skill in this conversation, acting as that stage's executor. |
| `task` | Render [the stage prompt](../../framework/references/prompts/stage-subagent.md.tpl) with the module, rule, skill and workdir from dispatch; launch it with `Task(run_in_background=True, prompt=<rendered>)`. |

After launching a background executor, query `decide` again so other ready work can proceed.
After an executor exits, pass `--wake <rule>:<run>` to `decide`. Carry out the returned action:

- `REAP`: run `kernel.py reap --module {module} --rule <rule> --run <run>`, then query again.
  Reap uses that run's result; an absent result is handled as an incomplete execution.
- `YIELD`: report the running work and wait for an executor completion before resuming.
- `ESCALATE`: resolve the reported decision under the authorization below; resume after recording
  it, or wait when information or a human decision is needed.
- `DONE`: report what the evidence establishes and its limits; complete signoff if it is in scope.

Executor completion comes from the host; `YIELD` and a result file alone do not establish that
an executor has exited. Wait for exit before waking or reaping its run. Use
`kernel.py status --module {module}` for a read-only status query. A failed CLI operation leaves
its reported cause to resolve; it does not constitute a completed action.

## Decisions and authorization

Assess the evidence and the user's actual authorization. Present the specific decision, basis and
unresolved issues when human input is needed, and wait for that decision. Within an existing
explicit delegation, decide and act in scope. A refusal or a reserved decision remains binding.
Record who decided and the authorization basis in `--provenance`, and the engineering grounds in
`--reason`. A host's permission to execute a command is separate from authorization for its decision.

## `ESCALATE` — resolve the decision

`decide` returns a reason and, where relevant, candidates. Inspect the evidence and identify what
needs deciding. `kernel.py consequences --module {module} --paths <path…>` shows the valid proofs
a proposed change would invalidate. Record a resolved repair attribution with:

```bash
kernel.py diagnose --module {module} --id <diag-id> \
  --subject-proof <failed proof> --subject-run <run> \
  --attribution <stage> --fix-owner <subject stage or its input producer> \
  --provenance "<decision maker and authorization>" --reason "<evidence and reasoning>" \
  [--supersedes <prior diag-id>]
```

This records `source=decision`; simulation-triage records `source=triage`. Both support the failed
stage itself or an input producer as repair owner. Omit ownership when the evidence cannot settle it.

## Closing: pin, reopen, signoff

When the task includes signoff, pass `--closing` to `decide`. Closure requires valid proofs,
`tool` or `endorsed` oracles and no unrecorded stage artifacts. Apply the authorization
above to each decision:

- `kernel.py pin --module {module} --rule <proof> --provenance "<decision maker and authorization>"
  --reason "<basis>"` endorses the oracle's current content. A content change expires that endorsement.
- `kernel.py reopen --module {module} --pin-ref <oracle_ref> --reason "<decision and basis>"`
  withdraws an endorsement.
- `decide --closing` returning `DONE` provides the basis ready for signoff. Assess the listed proofs,
  oracle fingerprints, requirement verdicts and inputs, alongside the effective tool and library
  conditions in the reports. Record the authorized
  decision with `kernel.py signoff --module {module} --provenance "<decision maker and authorization>"
  --reason "<basis>"`.

`DONE` alone is not signoff. `endorsed` means a recorded, content-bound endorsement; its provenance
identifies the decision maker and delegation, rather than implying personal review by the user.
Signoff applies to the accepted stage evidence. New conclusions need a new signoff under the
actual authorization; repeating collection or endorsement of unchanged evidence does not.
