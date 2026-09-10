---
name: simulation
description: Use when materializing and running a module's UVM TB from an approved verification plan (regression, coverage); not for plan authoring or RTL changes.
---

# UVM Simulation

Your sole responsibility: turn this module's approved verification plan into a running UVM
testbench, establish that the checks in it verify what the plan asked for, and close the run
through the `sim` CLI. You do that as a dispatcher over three sequential sub-Tasks, gating each
time on what the child left on disk rather than on what it says about itself.

You never author TB inline, never read the TB body, and never re-run heavy EDA: what you read is
status files, envelopes and paths.

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

`<skill>` is this skill's own base directory, named on the first line of this file.

`{workdir}/dispatch.json` carries the `inputs` table below, so `<key>` denotes a location and you
read `<key>/<subpath>`. None of it needs an existence check: the kernel dispatches you only once
each input's producer has recorded it and the fingerprint on disk still matches.

| Path | Use |
|---|---|
| `<scaffold>/tb-scaffold.json` + `<scaffold>/sequences.json` | The plan's judgment: which agent owns which `interface_group`, and what to run. `agents` / `sequences` / `tests` are what gets materialized into SV; `testpoints[]` carry which checks each one covers (`covers[]`), and what it drives (`intent`). `top` names the DUT. A sub-Task input: you hand over the path. |
| `<check_hints>/check-hints.json` + `<requirements>/requirements.json` | What every covered check observes and against what rule, and the requirement rows each check establishes; the env child reads both by id. The coverage gate reads its bounds from the requirements rows simulation judges. Sub-Task inputs: you hand over the paths. |
| `<intent>/` | The intent tree: the engineer's container — `brainstorm.md` plus whatever they delivered with it. Open a file here only when a requirements row points at it, and read it there rather than from any copy |
| `<plan>/verification-plan.md` | The human-readable plan the env-build child fills intent against. A sub-Task input; you hand over the path. |
| `<rtl>/rtl-files.json` | Per-child DUT file layout, which `bootstrap` turns into `rtl_filelist.f`. |
| `<spec>/top-io.json` + `<spec>/clocks.json` | The DUT boundary. `bootstrap` derives every vif signal, every clock generator and the reset polarity from these at render time — the scaffold does not restate them, so nothing you see in the TB can disagree with what specification declared. |

`dispatch.json` also carries `caused_by`, `scope` or `reasons` when the kernel knows what this round
is answering. Hand whichever is present to the env-build child as its edit scope, without reading
into it: `caused_by` names the records it reads itself — the failing envelopes, and the analysis that
attributed them — `scope` names the inputs that changed under you, `reasons` is a human's
judgment passed through unchanged. When none is present and `{workdir}` holds no prior TB, this is a first delivery and the
scope is the whole testbench.

Every round is the same round. `{workdir}` arrives holding your previous round's canonical output,
or empty on a first run, and you never branch on which: `bootstrap` writes only where a file is
missing. `check-review.md` is the one thing not carried forward, so the checks are judged
again from scratch whether or not the testbench changed.

Everything under `{workdir}` other than `result.json` is written by one of the children, and `finalize`
enumerates it into `artifacts[]` for you:

| Written by | What |
|---|---|
| env-build | `Makefile`, `env.sh`, `filelist.f`, `rtl_filelist.f`, `tb/uvm/**`, `scripts/**`, `tests/testlist.json`, and the smoke `regression-log.txt` with its per-test `logs/` |
| the check-adequacy reviewer | `check-review.md` |
| verify | the full-regress `regression-log.txt`, `structural-coverage.json`, `case-results.json`, `case-results-summary.md` |
| you, via `sim finalize` | `result.json` |

Per-file detail is in [`references/artifacts.md`](references/artifacts.md). One
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
`{workdir}`, `{module}`, `<skill>`, the scaffold-spec path, the verification-plan path, and this
round's edit scope. It bootstraps, fills every rendered `TODO(`, compiles, runs smoke, and
self-gates its own `STATUS: DONE` on `sim check-materialization` so a hollow TB cannot reach the
verify run.

On `STATUS: BLOCKED <reason>`, close the round and dispatch nothing further:

```bash
python3 <skill>/scripts/sim/__main__.py finalize --workdir {workdir} \
  --phase fail --fail-reason "<the child's reason, verbatim>"
```

Pass the child's own line through: it names where it stopped and why, and that sentence is the
whole of what the next reader gets. Do not compress it into a category.

Otherwise gate on the smoke run's own output, never on the child's prose about it. Read
`regression-log.txt`'s `RESULT <test> <PASS|FAIL>` lines, or the per-test `logs/<test>.status`
files. Do not use `sim finalize` as this gate: its coverage leg hard-fails before regress has
produced anything to measure.

- No `RESULT` line at all means `make simv` produced no `simv`, so nothing ran:
  `finalize --phase fail --fail-reason "make simv produced no simv; no test ran"`.
- Any non-`PASS` line: `finalize --phase fail --fail-reason "<which test, and its first error>"`,
  passing `--verify-verdict` with the reaped verdict so `failing_cases` reaches triage.
- Every line `PASS`: go to step 2.

### 2. Judge the checks

Dispatch one `Task(run_in_background=True)`, the check-adequacy reviewer, pointing its prompt at
[`references/check-review-task-contract.md`](references/check-review-task-contract.md)
and handing over the `{workdir}`, the scaffold-spec path, the DUT RTL filelist, and `{module}`.
It writes `{workdir}/check-review.md` itself. You never retype a finding: a review passed
through your hands is your judgment wearing the reviewer's name, and this gate decides your status.

On wake-up, reap its `STATUS:` line and read the file it left. Any finding whose heading ends
in `BLOCKING` stops the round; the rest are the reviewer telling you something it decided not to
stop for, so surface those as `⚠ <tp_id>` in your completion summary and move on.

Read it, do not adjudicate it. The mark is the reviewer's and you do not revisit it, and you do
not need to be trusted with that: `--phase final` reads the same headings before it will write a
pass, so a trip you walk past costs the round either way (step 4).

**Nothing marked:** go to step 3.

**Something marked:** dispatch one check-fix `Task(run_in_background=True)` per
[`references/check-fix-task-contract.md`](references/check-fix-task-contract.md), with
the flagged findings as its fix scope. It is the one that tries, so it is the one that decides
whether the check can be made adequate at all.

- `STATUS: DONE`: re-run this whole step over its work. There is no round cap and no build step in
  the loop; the reviewer is a static read, and a fix that breaks the compile surfaces at the verify
  child.
- `STATUS: BLOCKED`: it judges the defect to be in the plan rather than in the check. Fail out on
  its word, without re-running the reviewer, since nothing changed to re-judge:

```bash
python3 <skill>/scripts/sim/__main__.py finalize --workdir {workdir} \
  --phase fail --fail-reason "<the fixer's reason>"
```

Dispatch no verify child after that. The envelope carries the reason; the findings stay in
`check-review.md`, which is promoted beside it. The route from here is into
`simulation-triage`, which opens that record and reaches the attribution this stage does not
try to.

**No usable review** (`STATUS: BLOCKED`, or no file): close the round.

```bash
python3 <skill>/scripts/sim/__main__.py finalize --workdir {workdir} \
  --phase fail --fail-reason "check-adequacy review did not run: <the reviewer's reason>"
```

The review IS this gate. A round whose checks went unjudged has not established that they verify
anything, so it cannot pass — and you must not author a stand-in record saying so, because a
record with no `BLOCKING` in it reads to the gate as a clean review and would let exactly that
round through (checked: `check_review_flagged` returns `[]` on such a file). Dispatch no verify
child; the next round re-runs the reviewer.

### 3. Regress and cover

Dispatch one `Task(run_in_background=True)`, the verify child, pointing its prompt at
[`references/verify-task-contract.md`](references/verify-task-contract.md) and handing over the same
`{workdir}` (now holding the built TB and a compiled `simv`), the
scaffold-spec path, `{module}`, and `<skill>`. It runs the full regression and iterates stimulus against the
coverage bounds the requirements set, on the stimulus side of the stimulus/intent boundary
([`references/coverage-iteration.md`](references/coverage-iteration.md)). It repairs nothing: a
regress failure routes out with `failing_cases` for the caller to attribute.

Reap its `STATUS:` line and any failure JSON line. Anything other than a clean verdict closes the round
here, without step 4:

- a failing regress case: `finalize --phase fail --fail-reason "<the failing test and its error>"`;
- coverage gaps (`coverage` in its verdict): `finalize --phase fail --fail-reason "<which dimension
  is short, and whether the gaps sit inside any testpoint>"`;
- `STATUS: BLOCKED`: `finalize --phase fail --fail-reason "<the child's reason, verbatim>"`.

Pass `--verify-verdict <reaped verdict>.json` on the first two: that file is where `failing_cases`
and the coverage gap lists come from, and finalize carries across whichever of them it holds.

### 4. Close

On a clean verify verdict, run finalize. Do not hand-assemble the envelope, re-derive counts, or
copy a gate verdict across by hand.

```bash
python3 <skill>/scripts/sim/__main__.py finalize \
  --workdir {workdir} --phase final \
  --plan <scaffold> \
  --requirements <requirements>/requirements.json \
  --check-review {workdir}/check-review.md \
  [--fix-owner <rule>]
```

`--phase final` re-runs three gates over the workdir before it will write a pass: materialization,
the check-adequacy verdict off the review file you hand it, and coverage against the bounds the
requirements rows set. The
earliest failing one wins. So arriving here with an
un-dispositioned `gate=trip` costs you the round rather than passing it: finalize writes the same
envelope step 2's own fail-out would have. The smoke and verify verdicts
are the two it cannot re-derive, and each already wrote its own `status=fail` and skipped what
followed, so what reaches this command is only ever the most-failing verdict you hold.

Exit 0 means `result.json` was written, pass or fail. A non-zero exit is a program exception, not a
`status=fail` — including `--phase fail` with no `--fail-reason`, which finalize refuses rather than
writing an envelope the reap would reject. `fail_reason` rides on every fail and is absent on a
pass; on `--phase final` finalize derives it, and the companions follow from what the reaped verify
verdict actually carries.

**Naming the fix owner.** On a failure, add `--fix-owner <rule>`, the rule that must act. A
functional or latency miss the reference model confirms is `rtl-design`; a testpoint or scenario
gap is `simulation-plan`; a check-adequacy finding whose defect is in the spec is `specification`.
When you have read the logs and the reference model and still cannot attribute it, omit the flag.
This is the one stage whose unattributed failure dispatches `simulation-triage` for a deeper
analysis, so omitting it is an answer here rather than a shrug.

## Return Contract

Control returns to your caller, which decides what happens next from `{workdir}/result.json`
(`status ∈ {pass, fail}`). This skill emits no `STATUS:` line of its own; the ones the sub-Tasks
emit are consumed here and go no further.
