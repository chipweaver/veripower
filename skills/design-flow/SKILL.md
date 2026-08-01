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

Every verb prints a JSON envelope. An `ok: false` is a contract signal, not an obstacle:
hand the error to the user verbatim and stop that line of work. Never edit a file to make
the next call succeed — that edit is the isolation violation the Iron Rule names.

`kernel.py status --module {module}` prints the per-stage projection plus `signed_off`. It
is a read-only query for the user, outside the loop.

**Discipline:** call `decide` before every action. Two consecutive
state-mutating kernel calls (`dispatch` / `reap` / `diagnose` / `pin` / `reopen`) with no
`decide` between them is a bug — the executor for each action
runs, then you loop back to `decide`.

## Iron Rule

- Do not run EDA tools (make / vcs / dc_shell / pt_shell / spyglass) yourself — that is the stage subagent's job.
- Do not hand-edit `events.jsonl` or any stage `result.json` / artifact. A main-thread write to either is an isolation violation.
- **Scripts are black boxes — never Read their source.** Invoke `kernel.py` per this skill's documented command lines (flags via `<verb> --help`). Sole exception: debugging a suspected bug in the script itself.

## Session entry gate

Before entering the loop, `grep` the frontmatter of `asic/{module}/brainstorm.md`
(frontmatter only — do NOT load the body). If `Status` ≠ `approved`, reply "module
{module} has no approved brainstorm.md — run `Skill(veripower:brainstorm)` for {module},
then re-invoke design-flow" and **stop without entering the loop**: this is a pre-pipeline
user-input gate, not a pipeline failure.

The kernel already refuses to dispatch `specification` while the file is absent. What it
cannot see is an unapproved one, and that is the whole job of this gate.

## The execution loop — the 5 actions

`decide --objective <obj>` returns one action. Pass `--wake <rule>:<run>` when this turn
was triggered by a `<task-notification>` (values from its `<output-file>` / stage binding).

| action | execute |
|---|---|
| `REAP` | `kernel.py reap --module {module} --rule <rule> --run <run>`, then loop. `reap` derives the verdict from the run's own `result.json`; there is no verdict flag and you never supply one. |
| `DISPATCH`, `execution: main-thread` | `kernel.py dispatch ...` (see Dispatch below) → `Skill(veripower:<skill>)`, the skill from the dispatch return → loop. |
| `DISPATCH`, `execution: task` | `kernel.py dispatch ...` → render `framework/references/prompts/stage-subagent.md.tpl`, filling **every** template slot: `{module}`; the stage and skill lines from the dispatch return's `rule` / `skill` fields; `{workdir}` from the dispatch return. Every dispatch renders identically — what the round is about is in the kernel-written `{workdir}/dispatch.json`, not in the prompt → `Task(subagent_type="general-purpose", run_in_background=True, prompt=<rendered template>)` → loop. A stage skill is not an agent type; `general-purpose` is. |
| `DISPATCH`, `rule: simulation-triage` | The ambiguous-`simulation`-failure branch, and a task dispatch like any other: its `dispatch_args` already carry the failed run, which the kernel resolves into `dispatch.json` and into the diagnosis `subject.outcome_run`. |
| `YIELD` | Run the Dead in-flight check on the returned `in_flight[]`, then reply the in-flight list to the user and end the turn. (A triage-pending `YIELD` carries the triage run in `in_flight[]` — say a triage subagent is running.) |
| `DONE` | Reply a completion summary; end the turn. Under `signoff`, the action also carries `basis` — hand it to the user before proposing anything (see Pin, reopen, and signoff). |
| `ESCALATE` | See Escalation below. |

Branch the executor on `execution`, never on a hardcoded stage list: only the four
main-thread rules are `Skill()`-loaded, and `Skill(veripower:lint-cdc|synthesis|timing-analysis|power-analysis)`
in your tool history is a bug.

**Dispatch command.** A `DISPATCH` action carries `dispatch_args`, the exact argv for this
dispatch. Run `kernel.py` with it as-is — do not rebuild the flags from the action's other
fields, and do not add or drop any:

```bash
python3 framework/scripts/kernel.py <action.dispatch_args…>
```

The rework channels it carries (`--caused-by`, `--diagnosis-refs`) are coordinates, not
content: the kernel resolves them into `dispatch.json` so the target reads the failing
envelope and the human reasoning from a path it was given.

The call re-checks dispatchability at this instant, records the dispatch event, and returns
`{ok, rule, run, workdir, skill, execution}` — read `workdir` / `skill` / `execution` from
there.

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
    module is ready to close — but nothing is signed off until a human says so.
    **Lay out the returned `basis` first, per proof: the oracle ref and its live grade, the
    fingerprint a `human` pin named, the recorded tool identities, and the input set.** The
    gate says a signature is admissible; `basis` is the proposition being signed, and a
    human cannot take on what they were not shown. Then, only with their approval, run
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
`candidates[]`). Hand the user the reason **verbatim**, any `candidates`, and — to show the
blast radius of a proposed change — `kernel.py consequences --module {module} --paths <path…>`
(the currently-valid proofs a path change would invalidate). Give 2–3 concrete next steps.
The same applies to a subagent's own words: forward the text verbatim, because tidying it
into a cleaner escalation is how a real hold gets read as a soft one.

Recovery is **exclusively a human `kernel.py diagnose`** (source=human) — there is no
`resolve` verb, and you never auto-author a diagnosis (only triage mints one). Surface the
recovery command for the user to approve/author:

```bash
kernel.py diagnose --module {module} --id <diag-id> \
  --subject-proof <failed proof> --subject-run <run> \
  --attribution <stage> --fix-owner <producer inside the subject's input closure> \
  --evidence <path…> --provenance "<the identity that vouches>" --reason "<the reasoning>" \
  [--confidence high|medium|low] [--fix-locus <path…>] [--supersedes <prior diag-id>]
```

`--provenance` and `--reason` are both required and are different things: the bare identity
that vouches, and the reasoning, which is what `dispatch.json` carries verbatim to the fix
owner. `fix-owner` must produce an artifact inside the subject proof's transitive input
closure (the kernel rejects it otherwise); omitting `--fix-owner` records a self-pointing
attribution that `decide` will escalate again rather than auto-rebuild.
