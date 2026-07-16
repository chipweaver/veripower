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
| `REAP` | `kernel.py reap --module {module} --rule <rule> --run <run> [--subagent-output-file <output-file>]`, then loop. Pass `--subagent-output-file` (from the `<task-notification>`'s `<output-file>`) for every async Task reap so the trace is mirrored; the four main-thread skills complete synchronously and need no such file. `reap` derives the verdict from the run's own `result.json` (pass/fail; missing/unparseable/malformed/schema-invalid → `blocked`; a `produced_at` predating this run's dispatch → `blocked` `stale_result`, an unparseable `produced_at` → `blocked` `produced_at_unparseable` — a carried-in or mis-stamped envelope, so the stage must be re-run to author a fresh one) — never pass a verdict yourself. |
| `DISPATCH`, `execution: main-thread` | `kernel.py dispatch ...` (see Dispatch below) → `Skill(veripower:<skill>)` (the skill from the dispatch return) → loop. The next `decide` sees the finished run's `result.json` and returns `REAP`. |
| `DISPATCH`, `execution: task` | `kernel.py dispatch ...` → render `framework/references/prompts/stage-subagent.md.tpl`, filling **every** template slot: `{module}`; the stage and skill lines from the dispatch return's `rule` / `skill` fields; `{workdir}` from the dispatch return; on a rework dispatch also `{failing_result}` and `{directive_path}` → `Task(subagent_type="general-purpose", run_in_background=True, prompt=<rendered template>)` → loop. The next `decide` typically returns `YIELD` (the async run has no `result.json` yet) but may `DISPATCH` another eligible branch first — the loop is unconditional either way; a later `--wake` returns `REAP`. |
| `DISPATCH`, `rule: simulation-triage` | The ambiguous-`simulation`-failure branch. `kernel.py dispatch --module {module} --rule simulation-triage --objective <action.objective> --params '{"sim_run": <sim_run>}'` (take `<sim_run>` from the action's `params.sim_run` — the kernel feeds it to `store.inject_inputs` and the diagnosis `subject.outcome_run`) → render the template as for any other task dispatch (triage reads its failed run + design/rtl/plan locations from the injected `inputs.json`, so nothing is appended to its prompt) → `Task(subagent_type="general-purpose", run_in_background=True, ...)` → loop. |
| `YIELD` | Run the Dead in-flight check on the returned `in_flight[]`, then reply the in-flight list to the user and end the turn. (A triage-pending `YIELD` carries the triage run in `in_flight[]` — say a triage subagent is running.) |
| `DONE` | Reply a completion summary; end the turn. Under a `repair` objective, `DONE` means the failing proof re-verified (or nothing repairable remains — e.g. the re-verify was reaped `blocked`) — see Objective policy. |
| `ESCALATE` | See Escalation below. |

**Dispatch command.** From the `DISPATCH` action:

```bash
kernel.py dispatch --module {module} --rule <action.rule> \
  --objective <action.objective> \
  [--directive <file|->] [--diagnosis-refs id1,id2,...] [--params '{"sim_run": <sim_run>}']
```

It re-checks dispatchability at this instant, records the dispatch event, and returns
`{ok, rule, run, workdir, skill, execution}` — read `workdir` / `skill` / `execution` from
there. Branch the executor on `execution`, never on a hardcoded stage list.

## Objective policy

You carry the current `objective` as a session value and pass it to every `decide`.

- **Default `delivery`.** Forward-build the whole DAG.
- **`repair`.** When `decide` (under `delivery`) returns a `DISPATCH` with
  `needs_directive: true` (an auto-rebuild — a fix targeting an upstream producer, whether
  triage-forwarded, diagnosis-backed, or self-describing-route), execute that dispatch, then
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

## Directive authoring

`directive` is the one remaining judgment channel — a per-dispatch, reasoned instruction
that helps the target do its work; never a log/chat/dump slot, never data the subagent
already reads from canonical files. `kernel.py dispatch` writes it into
`<workdir>/directive.md` and records its path + digest in the dispatch event's `params`.

- **PPA targets → rtl-design directive.** Whenever you AUTHOR rtl-design's directive (a
  forward dispatch, or a self-describing-route rework) and `Design/specification/ppa.json`
  lists non-empty targets, transcribe each target's `dim` and numeric `target` value into
  the directive. rtl-design does not read `ppa.json` itself, so this is its only PPA channel.
  synthesis and power-analysis read `ppa.json` directly — inject nothing into their prompts.
- **Triage forward (verbatim).** For a `DISPATCH` with `triage_forward: true`, the directive
  IS the triage `result.json`, forwarded byte-for-byte:
  `--directive asic/{module}/Verification/simulation-triage/result.json`. LLM rewording is
  FORBIDDEN — `dispatch` copies the file content and records path + digest. This applies to
  whatever `fix_owner` the triage attribution points at.
- **Multi-diagnosis merge.** When the action carries several `diagnosis_refs`, the directive
  must incorporate every referenced diagnosis — none silently dropped. For triage sources,
  concatenate each source's `result.json` verbatim under a per-diagnosis attribution header
  and pass the merged file via `--directive <file>`.
- **Authored directive (non-triage).** For a `needs_directive` dispatch NOT from triage (a
  self-describing route rework), you write the fix instruction and pass it on stdin:
  `... | kernel.py dispatch ... --directive -`.

## Dead in-flight handling

On `YIELD`, inspect the returned `in_flight[]` (each entry is `{rule, run, has_result}`).
A run with `has_result: false` whose executor you confirm is **dead** (the Task subagent
crashed, exited without writing `result.json`, or its wake was lost) gets an explicit
`kernel.py reap --module {module} --rule <rule> --run <run> --subagent-output-file
<output-file>` (the path recorded at the Task launch) — with no `result.json` present,
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
| "I'll dump everything into the directive to be safe" | The directive carries only reasoned content that helps the target — never a dump, never data already in files the subagent reads. For a triage forward it is a byte-for-byte copy, never a hand-written summary. |
| "Let me re-warm the stage skill / tidy the subagent's wording before escalating" | Never pre-run `Skill(stage)` after dispatch; forward subagent text **verbatim** on escalation. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Edit-before-Read error ("File has not been read yet") on the main thread | You are inlining stage work — stop and move it back into a `Task` dispatch. |
| DISPATCH task fills `subagent_type="veripower:<stage>"` | A stage skill is not an agent type; use `general-purpose`. |
| Two mutating kernel calls with no `decide` between | Every action's executor is followed by a loop back to `decide`. Re-derive nothing by hand. |
| Passing a verdict / `--outcome` to `reap` | `reap` derives the verdict from `result.json` alone; there is no verdict flag. |
| Async reap omits `--subagent-output-file` | Self-audit both async reap sites (normal and dead-in-flight) carry it (best-effort; a missing/invalid path never raises, but the trace is then unmirrored). |

## Bundled References

- `${CLAUDE_PLUGIN_ROOT}/framework/scripts/kernel.py` — the state tool + decider (10 verbs). Invocation contract: this file + `<verb> --help` (each verb prints a JSON envelope).
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/prompts/stage-subagent.md.tpl`](../../framework/references/prompts/stage-subagent.md.tpl) — Task-dispatch prompt template.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common result envelope schema.
