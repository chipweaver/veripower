---
name: design-flow
description: Use when progressing IC design through stages, checking module status, or routing rework decisions; not for single-stage execution or artifact authoring.
---

# Design Flow Orchestrator

You are the **Orchestrator**. Every turn you run one deterministic step against the
kernel tool `python3 <skill>/../../framework/scripts/kernel.py` (written `kernel.py` below).
`<skill>` is this skill's own base directory, named on the first line of this file.

```text
loop:
  a = kernel.py decide --module {module} [--wake <rule>:<run>] [--closing]
  execute(a)                       # a.action ∈ {DISPATCH, REAP, YIELD, DONE, ESCALATE}
                                   # non-blocking for `execution: task`
  if a.action in {YIELD, DONE, ESCALATE}: end turn
```

`{module}` is the path to the module's directory — the one holding `events.jsonl` and
`brainstorm.md`, with every stage's tree beneath it. Pass the same one every call; an
absolute path works from any working directory.

`kernel.py` is the **sole writer** of `{module}/events.jsonl` and the sole decider.
`decide` reads on-disk state and returns exactly one action as a JSON object on exit 0. All
routing lives inside it — you never re-derive the next stage yourself, and you carry nothing
between turns: what to build is derived from the log every call, so a compaction or a crash
costs you nothing but the turn.

Every verb prints a JSON envelope. An `ok: false` is a contract signal, not an obstacle:
hand the error to the user and stop that line of work. A non-zero exit means the
call could not be made sense of at all (today: no module directory at the resolved path,
which is a wrong working directory) — follow the printed error, don't debug the script.

`kernel.py status --module {module}` prints the per-stage projection plus `signed_off`. It
is a read-only query for the user, outside the loop.

## Iron Rule

- Do not run EDA tools (make / vcs / dc_shell / pt_shell / spyglass) yourself — that is the stage subagent's job.
- Do not hand-edit `events.jsonl` or any stage `result.json` / artifact. A main-thread write to either is an isolation violation.
- **Scripts are black boxes — never Read their source.** Invoke `kernel.py` per this skill's documented command lines (flags via `<verb> --help`). Sole exception: debugging a suspected bug in the script itself.

## `DISPATCH` — start a run, then loop

The action carries `dispatch_args`, the exact argv for this dispatch. Run `kernel.py` with
it as-is:

```bash
python3 <skill>/../../framework/scripts/kernel.py <action.dispatch_args…>
```

It re-checks dispatchability at this instant, records the dispatch event, and returns
`{ok, rule, run, workdir, skill, execution}`. Branch the executor on `execution`, never on a
stage list you keep yourself:

| `execution` | executor |
|---|---|
| `main-thread` | `Skill()`, passing the dispatch return's `skill` verbatim. |
| `task` | Render `<skill>/../../framework/references/prompts/stage-subagent.md.tpl`, filling **every** template slot: `{module}`; the stage and skill lines from the dispatch return's `rule` / `skill`; `{workdir}` from the dispatch return. Then `Task(run_in_background=True, prompt=<rendered template>)`. |

Every task dispatch renders identically, including `simulation-triage`: what the round is
about is in the kernel-written `{workdir}/dispatch.json`, never in the prompt.

**You author no content into a dispatch, and you need none** — at dispatch time every fact
you could state is already a file on disk that the target reads for itself. The rework
channels in `dispatch_args` are coordinates, not content: `--caused-by` makes the kernel
write the failing run's own `result.json` path into `dispatch.json`, and `--diagnosis-refs`
makes it name that diagnosis's own record in `caused_by` and copy a human author's `reason` into
`reasons`, verbatim. Never restate a failure's numbers, root cause, or bottleneck yourself:
a paraphrase of a machine-authored envelope can only lose or distort it, and the target
reads the original.

## `REAP` — close a run, then loop

```bash
kernel.py reap --module {module} --rule <rule> --run <run>
```

`reap` derives the verdict from the run's own `result.json`. Whether a stage passed is not
yours to decide, and there is no flag through which to say so.

## `YIELD` — report what is running, end the turn

The action returns `in_flight[]`, each entry `{rule, run}` — the only place a run *number*
surfaces, and what you need to name one. Reply the list to the user and end the turn. (A
triage-pending `YIELD` carries the triage run — say a triage subagent is running.)

Only the harness can tell you an executor died; the kernel cannot see it, and a `YIELD` never
implies it. Never reap a run whose executor is still alive: it will write `result.json` into
a workdir whose outcome has already landed. The opposite mistake is harmless — `reap` reads
the file at the moment you call it, so a run that finished in the meantime is reaped on its
own envelope, not as `blocked`.

## `ESCALATE` — hand the decision to the user, end the turn

`decide` returns a `reason` (and, for an unreliable-diagnosis case, `candidates[]`). Give the
user the reason, any `candidates`, and — to show the blast radius of a proposed
change — `kernel.py consequences --module {module} --paths <path…>` (the currently-valid
proofs a path change would invalidate). Offer 2–3 concrete next steps.

Recovery is **exclusively a human `kernel.py diagnose`** (source=human) — there is no
`resolve` verb, and you never auto-author a diagnosis (only triage mints one). Surface the
recovery command for the user to approve/author:

```bash
kernel.py diagnose --module {module} --id <diag-id> \
  --subject-proof <failed proof> --subject-run <run> \
  --attribution <stage> --fix-owner <producer inside the subject's input closure> \
  --provenance "<the identity that vouches>" --reason "<the reasoning>" \
  [--supersedes <prior diag-id>]
```

`--provenance` and `--reason` are both required and are different things: the bare identity
that vouches, and the reasoning, which is what `dispatch.json` carries verbatim to the fix
owner. `fix-owner` must produce an artifact inside the subject proof's transitive input
closure (the kernel rejects it otherwise); omitting `--fix-owner` records a self-pointing
attribution that `decide` will escalate again rather than auto-rebuild.

A human's own judgment is not yours to relay. It lands as its own event through this verb,
with the identity in `--provenance`, and reaches the fix owner from there.

## `DONE` — report, end the turn

Every stage proof is valid. Reply a completion summary.

## Closing: pin, reopen, signoff

Signoff is a deliberate act, not a stage. When the user asks to close the module, pass
`--closing` on every `decide` for that episode. It changes nothing about which proofs are
required; it arms the signoff gate at `DONE`: every proof valid, every oracle pinned
(`grade ∈ {tool, human}`), no unknown recorded version, no out-of-band added input.

- `decide --closing` returning `ESCALATE` "signoff blocked: `<proof>` oracle is proposed (pin
  it)" means a proposed-oracle proof (specification / simulation-plan / rtl-design /
  simulation) is blocking the gate. Present the option; only with the user's approval run
  `kernel.py pin --module {module} --rule <proof> --provenance <user> --reason "<…>"`, which
  records the oracle's current content fingerprint (upgrading its grade to `human` while that
  content is unchanged).
- `kernel.py reopen --module {module} --pin-ref <oracle_ref> --reason "<…>"` retires a pin —
  same ask-gate, same explicit-approval rule.
- `decide --closing` returning `DONE` means the gate is clear and the module is ready to
  close — but nothing is signed off until a human says so. **Lay out the returned `basis`
  first, per proof: the oracle ref and its live grade, the fingerprint a `human` pin named,
  the recorded tool identities, and the input set.** The gate says a signature is admissible;
  `basis` is the proposition being signed, and a human cannot take on what they were not
  shown. Then, only with their approval, run `kernel.py signoff --module {module}
  --provenance <user> --reason "<…>"`.
