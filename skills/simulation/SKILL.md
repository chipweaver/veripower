---
name: simulation
description: Use when materializing and running a module's UVM TB from an approved verification plan (regression, coverage); not for plan authoring or RTL changes.
---

# UVM Simulation

Your sole responsibility: turn this module's approved verification plan into a running UVM
testbench, establish that the checks in it verify what the plan asked for, and close the run
through the `sim` CLI. You do that as a dispatcher over three sequential sub-Tasks, gating each
time on what the wave left on disk rather than on what it says about itself.

This skill runs on the main thread, invoked as `Skill(veripower:simulation)`. You never author TB
inline, never read the TB body, and never re-run heavy EDA: what you read is status files,
envelopes and paths.

## Iron Rule

- Write only under `{workdir}`. Every injected input location is read-only, as is every other
  stage's output.
- **Scripts are black boxes, never Read their source.** Invoke them per this skill's documented
  command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol
  (stderr, stdout verdict), not the source. Sole exception: debugging a suspected bug in a script
  itself.
- **The DUT RTL is never the reference.** No refmodel, scoreboard or checker may be written from
  reading RTL source: a golden model taken off the implementation mirrors its bugs and can never
  disagree with it, so a testbench built that way passes whatever the design does. RTL reaches this
  stage through the compile filelist and nowhere else.

## What you read, and who writes the rest

`{workdir}/dispatch.json` carries the `inputs` table below, so `<key>` denotes a location and you
read `<key>/<subpath>`. None of it needs an existence check: the kernel dispatches you only once
each input's producer has recorded it and the fingerprint on disk still matches.

| Path | Use |
|---|---|
| `<scaffold>/tb-scaffold.json` + `<scaffold>/sequences.json` | The TB contract. `agents` / `sequences` / `tests` are what gets materialized into SV; `testpoints[]` carry the check semantics (`inlined_check_hints[]`), what each testpoint drives (`intent`) and what it should reach (`bins`). `top` names the DUT. A sub-Task input: you hand over the path. |
| `<plan>/verification-plan.md` | The human-readable plan the env-build child fills intent against. A sub-Task input; you hand over the path. |
| `<rtl>/rtl-files.json` | Per-child DUT file layout, which `bootstrap` turns into `rtl_filelist.f`. Schema: `skills/rtl-design/references/rtl-files.schema.json`. |

`dispatch.json` also carries `caused_by`, `scope` or `reasons` when the kernel knows what this round
is answering. Hand whichever is present to the env-build child as its edit scope, without reading
into it: `caused_by` names the failing envelopes it reads itself, `scope` names the inputs that
changed or the anchors a diagnosis pointed at, `reasons` is a human's judgment passed through
unchanged. When none is present and `{workdir}` holds no prior TB, this is a first delivery and the
scope is the whole testbench.

Every round is the same round. `{workdir}` arrives holding your previous round's canonical output,
or empty on a first run, and you never branch on which: `bootstrap` writes only where a file is
missing. `conformance-review.json` is the one thing not carried forward, so the checks are judged
again from scratch whether or not the testbench changed.

Everything under `{workdir}` other than `result.json` is written by a wave, and `finalize`
enumerates it into `artifacts[]` for you:

| Written by | What |
|---|---|
| env-build (wave 1) | `Makefile`, `env.sh`, `filelist.f`, `rtl_filelist.f`, `tb/uvm/**`, `scripts/**`, `tests/testlist.json`, the smoke `regression-log.txt` with its per-test `logs/`, and `verify-handoff.json` |
| the conformance reviewer (wave 2) | `conformance-review.json` |
| verify (wave 3) | the full-regress `regression-log.txt`, `structural-coverage.json`, `case-results.json`, `coverage-summary.txt`, `case-results-summary.md` |
| you, via `sim finalize` | `result.json` |

Per-file detail is in [`references/artifact-contract.md`](references/artifact-contract.md). One
product is deliberately left out of `artifacts[]`: a failing test's full-hierarchy
`<test_id>.fsdb`, kept at the run-dir root for `simulation-triage` to open and dropped for tests
that passed.

## Workflow

Dispatch only Level-1 sub-Tasks; none of them dispatches one of its own. After each dispatch, send
a brief status and end the turn, then reap before the gate that follows. A sub-Task that comes back
`STATUS: BLOCKED` has crashed rather than reached a verdict: record it as this stage's `status=fail`
and leave the re-dispatch to a repair round.

### 1. Build the TB, then gate on the smoke run

Dispatch one `Task(run_in_background=True)`, the env-build child, pointing its prompt at
[`references/env-task-contract.md`](references/env-task-contract.md) and handing over paths only:
`{workdir}`, `{module}`, the scaffold-spec path, the verification-plan path, and this round's edit
scope. It bootstraps, fills every rendered `TODO(` within the Rule A repair boundary
([`references/repair-boundaries.md`](references/repair-boundaries.md)), compiles, runs smoke, and
self-gates its own `STATUS: DONE` on `sim check-materialization` so a hollow TB cannot reach the
verify run.

On `STATUS: BLOCKED <reason>`, close the round and dispatch nothing further:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py finalize --workdir {workdir} \
  --module <module> --phase env-blocked --failure-phase <compile|smoke|prerequisite> \
  --fail-reason "<reason>"
```

The child's reason string picks `--failure-phase`: `compile` or `smoke` for a Rule A semantic
block, `prerequisite` for an incomplete `inlined_check_hints[]`, which is a plan defect rather than
one of yours.

Otherwise gate on the smoke run's own output, never on the child's prose about it. Read
`regression-log.txt`'s `RESULT <test> <PASS|FAIL>` lines, or the per-test `logs/<test>.status`
files. Do not use `sim finalize` as this gate: its coverage leg hard-fails before regress has
produced anything to measure.

- No `RESULT` line at all means `make simv` produced no `simv`, so nothing ran: `finalize --phase
  smoke --failure-phase compile`.
- Any non-`PASS` line: `finalize --phase smoke --failure-phase smoke`, passing `--verify-verdict`
  with the reaped verdict so `failing_cases` reaches triage.
- Every line `PASS`: go to step 2.

### 2. Judge the checks

Dispatch one `Task(run_in_background=True)`, the conformance reviewer, pointing its prompt at
[`references/conformance-review-task-contract.md`](references/conformance-review-task-contract.md)
and handing over the `{workdir}`, the scaffold-spec path, the DUT RTL filelist, and `{module}`.
It writes `{workdir}/conformance-review.json` itself. You never retype a finding: a review passed
through your hands is your judgment wearing the reviewer's name, and this gate decides your status.

On wake-up, reap its `STATUS:` line and validate the file it left:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py validate-review --review {workdir}/conformance-review.json
```

Exit 0 prints one line, `{"gate": "trip"|"clear", "flagged": [...]}`. The gate is
`any(blocking)` over the reviewer's own calls, computed rather than eyeballed. Non-blocking
findings never appear in it: surface those as `⚠ <tp_id>` in your completion summary and move on.

**`gate=clear`:** go to step 3.

**`gate=trip`:** dispatch one conformance-fix `Task(run_in_background=True)` per
[`references/conformance-fix-task-contract.md`](references/conformance-fix-task-contract.md), with
the flagged findings as its fix scope. It is the one that tries, so it is the one that decides
whether the check can be made adequate at all.

- `STATUS: DONE`: re-run this whole step over its work. There is no round cap and no build step in
  the loop; the reviewer is a static read, and a fix that breaks the compile surfaces at the verify
  wave.
- `STATUS: BLOCKED`: it judges the defect to be in the plan rather than in the check. Fail out on
  its word, without re-running the reviewer, since nothing changed to re-judge:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py finalize --workdir {workdir} \
  --module <module> --phase conformance --fail-reason "<the fixer's reason>" \
  --conformance-review {workdir}/conformance-review.json
```

Dispatch no verify wave after that. The route from here is `failure_phase=conformance` into
`simulation-triage`, which supplies the confidence this stage does not try to.

**No usable review** (`STATUS: BLOCKED`, no file, or a non-zero `validate-review`): do not gate on
it, and do not let it disappear either. Write the record yourself and go to step 3:

```json
{"findings": [{"tp_id": "-", "location": "-", "blocking": false,
               "finding": "review wave failed: <reason>; the checks went unjudged this round"}]}
```

This is the only record you author, and it says that no review happened, not what a review found.

### 3. Regress and cover

Dispatch one `Task(run_in_background=True)`, the verify child, pointing its prompt at
[`references/verify-task-contract.md`](references/verify-task-contract.md) and handing over the same
`{workdir}` (now holding the built TB, a compiled `simv` and `verify-handoff.json`), the
scaffold-spec path, and `{module}`. It runs the full regression and iterates stimulus against the
coverage thresholds within the Rule B boundary
([`references/coverage-iteration.md`](references/coverage-iteration.md)). It repairs nothing: a
regress failure routes out with `failing_cases` for the caller to attribute.

Reap its `STATUS:` line and its JSON line. Anything other than a clean verdict closes the round
here, without step 4:

- a failing regress case: `finalize --phase regress --failure-phase regress --plan <scaffold>`;
- Rule B gaps (`failure_phase=coverage` in its verdict): `finalize --phase regress
  --failure-phase coverage --plan <scaffold>`;
- `STATUS: BLOCKED`: `finalize --phase verify-blocked`.

Pass `--verify-verdict <reaped verdict>.json` on the first two: that file is where `failing_cases`
and the coverage gap lists come from.

### 4. Close

On a clean verify verdict, run finalize. Do not hand-assemble the envelope, re-derive counts, or
copy a gate verdict across by hand.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py finalize \
  --workdir {workdir} --module <module> --phase final \
  --plan <scaffold> \
  --thresholds ${CLAUDE_SKILL_DIR}/defaults.yaml \
  --conformance-review {workdir}/conformance-review.json \
  --verify-verdict {workdir}/<reaped-verify-verdict>.json \
  [--fix-owner <rule>]
```

`--phase final` re-runs three gates over the workdir before it will write a pass: materialization,
the conformance verdict off the review file you hand it, and coverage against the thresholds. The
earliest failing one wins and becomes `failure_phase`. So arriving here with an un-dispositioned
`gate=trip` costs you the round rather than passing it: finalize writes the same
`failure_phase=conformance` envelope step 2's own fail-out would have. The smoke and verify verdicts
are the two it cannot re-derive, and each already wrote its own `status=fail` and skipped what
followed, so what reaches this command is only ever the most-failing verdict you hold.

Exit 0 means `result.json` was written, pass or fail. A non-zero exit is a program exception, not a
`status=fail`. `failure_phase` and `fail_reason` ride on every fail and are absent on a pass;
finalize derives both from the `--phase` you called.

**Naming the fix owner.** On a failure, add `--fix-owner <rule>`, the rule that must act. A
functional or latency miss the reference model confirms is `rtl-design`; a testpoint or scenario
gap is `simulation-plan`; a conformance finding whose defect is in the spec is `specification`.
When you have read the logs and the reference model and still cannot attribute it, omit the flag.
This is the one stage whose unattributed failure dispatches `simulation-triage` for a deeper
analysis, so omitting it is an answer here rather than a shrug.

## Return Contract

Control returns to your caller, which decides what happens next from `{workdir}/result.json`
(`status ∈ {pass, fail}`). This skill emits no `STATUS:` line of its own; the ones the sub-Tasks
emit are consumed here and go no further.
