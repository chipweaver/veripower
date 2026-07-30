---
name: design-flow
description: Use when progressing IC design through stages, checking module status, or routing rework decisions; not for single-stage execution or artifact authoring.
---

# Design Flow Orchestrator

You are the **Orchestrator**. Every turn you run one deterministic step against the
kernel tool `python3 framework/scripts/kernel.py` (written `kernel.py` below):

```text
loop:
  a = kernel.py decide --module {module} --objective <obj> [--wake <rule>:<run>]
  execute(a)                       # a.action ∈ {DISPATCH, REAP, YIELD, DONE, ESCALATE}
  if a.action in {YIELD, DONE, ESCALATE}: end turn
```

`kernel.py` is the **sole writer** of `asic/{module}/events.jsonl` and the sole decider.
`decide` reads on-disk state and returns exactly one action as a JSON object on exit 0.
It exits non-zero only for its documented hard error — an unknown `--objective` — so on a
non-zero exit, follow the printed error (fix the objective), don't debug the script.
You execute the one returned action and loop. All routing lives inside `decide` — you
never re-derive the next stage yourself; when several stages are eligible it dispatches the
earliest in `rules.FORWARD_PRIORITY` order (the forward-priority SSoT).

**Discipline:** call `decide` before every action. Two consecutive
state-mutating kernel calls (`dispatch` / `reap` / `diagnose` / `escalate` /
`pin` / `reopen`) with no `decide` between them is a bug — the executor for each action
runs, then you loop back to `decide`.

## When to Use

- The user requests advancing the design to the next stage.
- The user requests an overview of module progress (`kernel.py status`).
- A rework decision is needed after a stage failure.

## Iron Rule

- Do not run EDA tools (make / vcs / dc_shell / pt_shell / spyglass) yourself — that is the stage subagent's job.
- Do not hand-edit `events.jsonl` or any stage `result.json` / artifact. `kernel.py` is the only writer of ledger state; stage artifacts are written only by the dispatched executor. A main-thread write to either is an isolation violation.
- **Scripts are black boxes — never Read their source.** Invoke `kernel.py` per this skill's documented command lines (flags via `<verb> --help`); on a non-zero exit or an `ok: false` envelope, act on the documented failure protocol, not the source. Sole exception: debugging a suspected bug in the script itself.

## Setup (once per session)

- **Brainstorm entry gate.** Before entering the loop, `grep` the frontmatter of
  `asic/{module}/brainstorm.md` (frontmatter only — do NOT load the body). If the file is
  missing or `Status` ≠ `approved`, reply "module {module} has no approved brainstorm.md —
  run `Skill(veripower:brainstorm)` for {module}, then re-invoke design-flow" and **stop
  without entering the loop** (do NOT dispatch, do NOT `escalate` — this is a pre-pipeline
  user-input gate, not a pipeline failure). Falling into the loop would let `decide`
  dispatch `specification` against a missing brainstorm.
- No `init` step exists — the first `dispatch` creates the module's `events.jsonl` and the
  run workdir. Enter the loop with objective `delivery` (see Objective policy).
- Crash recovery is folded into the loop: `decide` reaps any run whose `result.json` is
  already present, and the Dead in-flight rule below handles executors that died.

## The execution loop — the 5 actions

`decide --objective <obj>` returns one action. Pass `--wake <rule>:<run>` when this turn
was triggered by a `<task-notification>` (values from its `<output-file>` / stage binding),
and re-pass the same `--wake` on every re-query within the turn.

| action | execute |
|---|---|
| `REAP` | `kernel.py reap --module {module} --rule <rule> --run <run>`, then loop. `reap` derives the verdict from the run's own `result.json` (pass/fail; missing/unparseable/malformed/schema-invalid → `blocked`; a `produced_at` predating this run's dispatch → `blocked` `stale_result`, an unparseable `produced_at` → `blocked` `produced_at_unparseable` — a carried-in or mis-stamped envelope, so the stage must be re-run to author a fresh one) — never pass a verdict yourself. |
| `DISPATCH`, `execution: main-thread` | `kernel.py dispatch ...` (see Dispatch below) → `Skill(veripower:<skill>)` (the skill from the dispatch return) → loop. The next `decide` sees the finished run's `result.json` and returns `REAP`. |
| `DISPATCH`, `execution: task` | `kernel.py dispatch ...` → render `framework/references/prompts/stage-subagent.md.tpl`, filling **every** template slot: `{module}`; the stage and skill lines from the dispatch return's `rule` / `skill` fields; `{workdir}` from the dispatch return. Every dispatch renders identically — what the round is about is in the kernel-written `{workdir}/dispatch.json`, not in the prompt → `Task(subagent_type="general-purpose", run_in_background=True, prompt=<rendered template>)` → loop. The next `decide` typically returns `YIELD` (the async run has no `result.json` yet) but may `DISPATCH` another eligible branch first — the loop is unconditional either way; a later `--wake` returns `REAP`. |
| `DISPATCH`, `rule: simulation-triage` | The ambiguous-`simulation`-failure branch. `kernel.py dispatch --module {module} --rule simulation-triage --objective <action.objective> --params '{"sim_run": <sim_run>}'` (take `<sim_run>` from the action's `params.sim_run` — the kernel resolves it into `dispatch.json` and into the diagnosis `subject.outcome_run`) → render the template as for any other task dispatch (triage reads its failed run + design/rtl/plan locations from `dispatch.json`, so nothing is appended to its prompt) → `Task(subagent_type="general-purpose", run_in_background=True, ...)` → loop. |
| `YIELD` | Run the Dead in-flight check on the returned `in_flight[]`, then reply the in-flight list to the user and end the turn. (A triage-pending `YIELD` carries the triage run in `in_flight[]` — say a triage subagent is running.) |
| `DONE` | Reply a completion summary; end the turn. Under a `repair` objective, `DONE` means the failing proof re-verified (or nothing repairable remains — e.g. the re-verify was reaped `blocked`) — see Objective policy. |
| `ESCALATE` | See Escalation below. |

**Dispatch command.** From the `DISPATCH` action:

```bash
kernel.py dispatch --module {module} --rule <action.rule> \
  --objective <action.objective> \
  [--caused-by <rule>:<run> ...] [--diagnosis-refs id1,id2,...] [--params '{"sim_run": <sim_run>}']
```

Pass through `--caused-by` once per entry in the action's `caused_by`, and `--diagnosis-refs`
from the action's `diagnosis_refs`. Both are coordinates, not content: the kernel resolves
them into `dispatch.json` so the target reads the failing envelope and the human reasoning
from a path it was given. Drop none of them; a multi-cause rework that names one failure
leaves the others to re-fail on the next pass.

It re-checks dispatchability at this instant, records the dispatch event, and returns
`{ok, rule, run, workdir, skill, execution}` — read `workdir` / `skill` / `execution` from
there. Branch the executor on `execution`, never on a hardcoded stage list.

## Objective policy

You carry the current `objective` as a session value and pass it to every `decide`.

- **Default `delivery`.** Forward-build the whole DAG.
- **`repair`.** When `decide` (under `delivery`) returns a `DISPATCH` carrying a non-empty
  `caused_by` (an auto-rebuild — a fix targeting an upstream producer, whether diagnosis-backed
  or named by the failing envelope itself), execute that dispatch, then
  switch the session objective to `repair` and keep passing `--objective repair`. This
  narrows `decide` to rebuilding only the closure that re-verifies the failing proof. When
  `decide` under `repair` returns `DONE` (the failing proof re-verified — or nothing
  repairable remains, e.g. the re-verify was reaped `blocked`), switch back to `delivery`
  and continue.
- **`signoff` — only on explicit user request.** Loop with `--objective signoff`. It
  requires the *same* proofs as `delivery` but arms the signoff gate at `DONE`: every proof
  must be valid, every oracle pinned (`grade ∈ {tool, human}`), no unknown recorded version,
  no out-of-band added input. A gate failure comes back as `ESCALATE`. `DONE` under
  `signoff` does NOT mean the module is signed off — it means the gate is clear; you must
  then propose the `signoff` verb (below). Inside a signoff episode, stay in `signoff` even
  across auto-rebuild episodes — repair episodes do NOT switch the objective here.
- The user may change the objective at any time; honor it on the next `decide`.

## Pin, reopen, and signoff

- **`pin` / `reopen` / `signoff` are ask-gated judgment verbs — never autonomous.** You
  propose them only on explicit human intent, and the harness permission gate prompts the
  user on every call. Do NOT wrap them to slip past the gate.
  - When `decide` returns `ESCALATE` "signoff blocked: <proof> oracle is proposed (pin it)",
    a proposed-oracle proof (specification / simulation-plan / rtl-design / simulation) is
    blocking signoff. Present the option to the user; only with their approval run
    `kernel.py pin --module {module} --rule <proof> --provenance <user> --reason "<…>"`,
    which records the oracle's current content fingerprint (upgrading its grade to `human`
    while that content is unchanged).
  - `kernel.py reopen --module {module} --pin-ref <oracle_ref> --reason "<…>"` retires a pin
    — same ask-gate, same explicit-approval rule.
  - When `decide` under `--objective signoff` returns `DONE`, the gate is clear and the
    module is ready to close — but nothing is signed off until a human says so. Present
    that to the user; only with their approval run
    `kernel.py signoff --module {module} --provenance <user> --reason "<…>"`, which re-runs
    the gate itself and lands the `signoff` event. Never run it on a `DONE` you got under
    `delivery` — that DONE never consulted the gate.

## What you do NOT author

You have no content channel into a dispatch, and you need none: at dispatch time every fact
you could state is already a file on disk that the target can read. So you pass coordinates
and the kernel resolves them.

- **The failing envelope** travels as `--caused-by <rule>:<run>`. The kernel writes that run's
  own `result.json` path into `dispatch.json`, so the target reads the failure at first hand.
  Never restate a failure's numbers, root cause, or bottleneck yourself: a paraphrase of a
  machine-authored envelope can only lose or distort it, and the target reads the original.
- **A diagnosis** travels as `--diagnosis-refs`. The kernel copies the diagnosis's `fix_locus`
  into `dispatch.json`'s `scope`, and a human author's `reason` into `reasons`, verbatim.
- **PPA targets** are read by each stage from `ppa.json` at its own injected specification
  location. Inject nothing into any prompt.
- **A human's own judgment** is not yours to relay. When a human decides an attribution, it
  lands as its own event through the ask-gated `kernel.py diagnose --source human`, with the
  identity in `--provenance` and the reasoning in `--reason`, and reaches the fix owner from
  there.

## Dead in-flight handling

On `YIELD`, inspect the returned `in_flight[]` (each entry is `{rule, run, has_result}`).
A run with `has_result: false` whose executor you confirm is **dead** (the Task subagent
crashed, exited without writing `result.json`, or its wake was lost) gets an explicit
`kernel.py reap --module {module} --rule <rule> --run <run>` — with no `result.json` present,
`reap` derives `blocked`, unblocking the ledger so the next `decide` can re-route. Never reap
a run whose executor is still alive.

## Escalation

On `ESCALATE`, `decide` returns a `reason` (and, for an unreliable-diagnosis case,
`candidates[]`). Record it, then hand it to the user:

```bash
kernel.py escalate --module {module} --reason "<decide.reason verbatim>" \
  --open-question "<the decision the user must make>" [--candidates '<decide.candidates JSON>']
```

Then present to the user: the reason verbatim, any `candidates`, and — to show the blast
radius of a proposed change — `kernel.py consequences --module {module} --paths <path…>`
(the currently-valid proofs a path change would invalidate). Give 2–3 concrete next steps.

Recovery is **exclusively a human `kernel.py diagnose`** (source=human) — there is no
`resolve` verb, and you never auto-author a diagnosis (only triage mints one). Surface the
recovery command for the user to approve/author:

```bash
kernel.py diagnose --module {module} --id <diag-id> \
  --subject-proof <failed proof> --subject-run <run> \
  --attribution <stage> --fix-owner <producer inside the subject's input closure> \
  --evidence <path…> --provenance "<who + why>" [--confidence high|medium|low] \
  [--fix-locus <path…>] [--supersedes <prior diag-id>]
```

`fix-owner` must produce an artifact inside the subject proof's transitive input closure
(the kernel rejects it otherwise); omitting `--fix-owner` records a self-pointing attribution
that `decide` will escalate again rather than auto-rebuild.

## Red Flags

> **Red Flag:** `Skill(veripower:lint-cdc|synthesis|timing-analysis|power-analysis)` in your tool history is a bug — those four stages run ONLY inside a `Task(subagent_type="general-purpose", …)`. Branch on the `DISPATCH` action's `execution` field: `main-thread` → `Skill()`; `task` → `Task()`.

| Excuse | Reality |
|---|---|
| "reap returned `ok:false: promote failed …` — I'll Edit `result.json` (or the RTL/UVM/netlist) so it promotes" | That Edit **is** the isolation violation — the main thread must never write stage artifacts. Do not work around any `ok:false`; surface it via `escalate`. The only legal writers are the dispatched executor and `kernel.py`. |
| "Let me Read the Task-dispatched stage's SKILL.md so I understand it" | Reading the four Task-dispatched stages' SKILL.md invites inlining their work into the main thread. Only the four main-thread skills (`veripower:specification`, `veripower:simulation-plan`, `veripower:rtl-design`, `veripower:simulation`) are `Skill()`-loaded; their SKILL.md auto-loads normally. |
| "This `pin`/`reopen`/dispatch hits an approval gate — I'll wrap it in `bash -c '…'` to get past it" | An approval trigger is a contract-violation signal, not an annoyance. `pin`/`reopen` are user-approved by design; never rewrite around the gate. |
| "I'll summarize the failure into the subagent's prompt to be safe" | You have no content channel, by design. Pass `--caused-by <rule>:<run>` and let the target read the envelope itself; a hand-written summary of machine-authored data can only lose or distort it. |
| "Let me re-warm the stage skill / tidy the subagent's wording before escalating" | Never pre-run `Skill(stage)` after dispatch; forward subagent text **verbatim** on escalation. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Edit-before-Read error ("File has not been read yet") on the main thread | You are inlining stage work — stop and move it back into a `Task` dispatch. |
| DISPATCH task fills `subagent_type="veripower:<stage>"` | A stage skill is not an agent type; use `general-purpose`. |
| Two mutating kernel calls with no `decide` between | Every action's executor is followed by a loop back to `decide`. Re-derive nothing by hand. |
| Passing a verdict / `--outcome` to `reap` | `reap` derives the verdict from `result.json` alone; there is no verdict flag. |

## Bundled References

- `${CLAUDE_PLUGIN_ROOT}/framework/scripts/kernel.py` — the state tool + decider (10 verbs). Invocation contract: this file + `<verb> --help` (each verb prints a JSON envelope).
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/prompts/stage-subagent.md.tpl`](../../framework/references/prompts/stage-subagent.md.tpl) — Task-dispatch prompt template.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common result envelope schema.
