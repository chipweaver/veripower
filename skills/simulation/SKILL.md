---
name: simulation
description: Use when materializing and running a module's UVM TB from an approved verification plan (regression, coverage); not for plan authoring or RTL changes.
---

# UVM Simulation

Your sole responsibility: orchestrate the UVM verification flow as a thin dispatcher over
three sequential sub-Tasks — env-build (bootstrap + fill scaffold + compile + smoke) → a
deterministic smoke gate → a conformance gate (LLM check-adequacy review; Step 4) →
verify (regress + coverage iterate + summary). The main thread
reads only envelopes / status files / paths; it NEVER reads the TB body, never authors TB inline, and
never re-runs heavy EDA. Each sub-Task's repair authority is bound by **Rule A** (scaffold vs.
semantics, env phase) and **Rule B** (stimulus vs. intent, verify phase).

**Load mode:** this skill runs main-thread, invoked via `Skill(veripower:simulation)` by its caller
(not dispatched as a Task subagent). It uses the Task tool for three sequential fan-out waves (one
sub-Task each — Wave 1 env-build, Wave 2 conformance reviewer, Wave 3 verify), each followed by a
deterministic main-thread gate (the smoke gate after Wave 1, the conformance gate after Wave 2, the
scripted finalize after Wave 3); the main thread never authors TB inline.

## When to Use

- First-time end-to-end run against the plan.
- Incremental re-run after an RTL or plan change.
- A repair dispatch after a downstream stage routes back.

## Iron Rule

- The injected input locations (`<rtl>`, `<plan>`, `<scaffold>` — from `inputs.json`) are read-only
  canonical: never modify anything under them (or any other stage's canonical output); the only
  files you write live under `{workdir}`. Shared by both sub-Tasks — see each contract's
  Prohibitions. RTL-class issues in particular belong to the RTL editing stage — do not exceed
  your authority by fixing them here.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.
- **Never read RTL source to author the TB.** The TB / refmodel / checker derive their behavior solely
  from the sim-plan exit docs (`verification-plan.md` + `scaffold-specification.json`); the DUT RTL is
  the thing under test, never the golden reference. Reading RTL to write a check makes the refmodel
  mirror the DUT -- circular verification that can never catch an RTL bug. RTL enters only mechanically,
  via the compile filelist. (Binding detail: `references/env-task-contract.md` / `references/inlined-check-hints.md`.)

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root (shared by all sub-Tasks). |
| `{module}` | Module name. |
| `{failing_result}` | Optional. The failed stage's canonical `result.json` path (`stage_specific` shape per that stage's schema); when present, it is one of Step 1's edit-scope sources — passed to the env-build child to narrow this round's rewrite scope. |
| `{directive_path}` | Optional. Fix-scope hint file — takes priority over `{failing_result}`; passed through to the env-build child. |

### External reference inputs

Each read-only upstream input's location is injected — read `inputs.json` in your `{workdir}`;
below, `<key>` denotes that input's location, so you read `<key>/<subpath>`.

| Path | Schema / Format | Use |
|---|---|---|
| `<rtl>/filelist.txt` | text | DUT RTL compile list — bootstrap rebases it into `rtl_filelist.f` (fails when missing); RTL enters only mechanically via this list (Iron Rule). |
| `<plan>/verification-plan.md` | Custom markdown | env-build sub-Task input — passed by path; the main thread never reads the body. |
| `<scaffold>/scaffold-specification.json` | Custom JSON | TB scaffold contract — sub-Task input; the main thread asserts existence only; also the `top` inference source for `sim bootstrap` (falls back to the `<rtl>` filelist). |

When `{failing_result}` is injected, you pass its path (and any
`{directive_path}`) to the env-build sub-Task, which reads the failed stage's
`stage_specific` to drive this round's rewrite scope.

## Output Artifacts

`result.json` is the only artifact the main thread writes; every other artifact is produced by a
sub-Task in the shared `{workdir}` and is listed in `result.json.artifacts[]` by the main thread at
finalize. The env / verify phase split of the workdir artifacts is in
[`references/artifact-contract.md`](references/artifact-contract.md).

| Path (relative to `{workdir}`) | Schema / Format | Owner | Use |
|---|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | main thread | This stage's status contract (`failure_phase` / `coverage_gaps`, etc.). |
| `Makefile` / `env.sh` / `filelist.f` / `rtl_filelist.f` / `tb/uvm/` / `scripts/` / `tests/testlist.json` | per `artifact-contract.md` | env-build | TB infra + materialized UVM (bound by Rule A). |
| `regression-log.txt` / `structural-coverage.json` / `coverage-summary.txt` / `case-results-summary.md` | per `artifact-contract.md` | verify | Regression log + machine-readable structural coverage (gate source for `sim finalize`) + summaries. |
| `verify-handoff.json` | per `env-task-contract.md` | env-build | Per-testpoint check-intent digest for the verify phase, written fresh every round. |
| `conformance-review.json` | per `references/conformance-review.schema.json` | conformance gate (main thread) | Per-testpoint check-adequacy findings (gate source for Step 4); promoted advisory artifact. |

> Every promoted path MUST appear in `result.json.artifacts[]`, otherwise it will not be promoted to
> canonical (external read-only consumption of canonical `filelist.f` / `tb/uvm/`, etc. will fail).
>
> Failing tests additionally retain a full-hierarchy `<test_id>.fsdb` (dumped via `-ucli`
> `$fsdbDumpvars`) at the run-dir root for `simulation-triage`'s L1 waveform query — per-run, **not
> promoted**, and gc-on-pass keeps one only for failing tests (see `references/artifact-contract.md`).

The promoted full set is enumerated by `sim finalize` (`enumerate_artifacts`) — this table is the contract surface; the per-phase inventory lives in `artifact-contract.md`.

## Workflow (thin dispatcher; three sequential waves + smoke gate + scripted finalize)

### Fan-out Dispatch Contract

Framework-mechanism rules (dispatch-and-wait below is the main-thread lifecycle); enforced at the
framework / harness layer (the wake protocol; writes confined to `runs/N/`, promoted on reap), not by this skill's
Completion Gate.

- **No Level 2 dispatch:** this skill dispatches only Level-1 sub-Tasks (env-build, conformance reviewer,
  then verify) — the audit boundary.
- **Dispatch-and-wait:** after dispatching a wave's sub-Task, send a brief status and end the turn;
  the harness wakes the main thread per completion (the wake is to the harness, not back to the
  caller). Reap the sub-Task on its wake before the downstream gate/wave.
- **No `kernel.py`:** this skill does not call `kernel.py`.
- **Sub-Task `STATUS: BLOCKED` carve-out:** a sub-Task's last-line `STATUS: BLOCKED <reason>` is a
  harness-level signal, distinct from the `result.json.status` enum (`pass`/`fail` only); the main
  thread maps it to `status=fail` + `fail_reason` and defers re-dispatch to a later repair dispatch.

### Step 1: Prerequisite + scope

Assert the plan artifacts (`<plan>/verification-plan.md` + `<scaffold>/scaffold-specification.json`)
exist. If either is missing, run `sim finalize --workdir {workdir} --module <module> --phase
prerequisite --fail-reason "external reference missing: <path>"` and return without dispatching. The
main thread does not read the scaffold-spec / verification-plan body — only path existence.

Pre-gate `{failing_result}` readability before dispatching any wave: if the trigger path is
unreadable, run `sim finalize --workdir {workdir} --module <module> --phase prerequisite
--fail-reason "failing_result not readable"` and return without dispatching.

**Every round is homogeneous — there is no branch to select.** The framework's
`carry_self` has already carried your previous round's TB (`Makefile` / `env.sh` / `filelist.f` /
`tb/uvm/**` / `scripts/**` / `tests/testlist.json` / `regression-log.txt` / `verify-handoff.json` —
everything except `conformance-review.json`, which is deliberately never carried and is always
re-derived) into `{workdir}` before you were dispatched, whenever a prior canonical run exists.
Whether a TB was carried is a disk fact, not a verdict you compute: a carried `Makefile` means this
round is a rework, its absence means a genuine first run — the `bootstrap` verb (Step 2) tests for
this itself via its no-clobber deploy, so you never branch on it here. Every round runs the same
sequence: dispatch env-build (Step 2) → smoke gate (Step 3) → **re-judge conformance** (Step 4 —
dispatched every round, never skipped) → verify (Step 5) → finalize (Step 6).

Determine this round's edit scope for the env-build child (Step 2) from the first available source:
1. `{directive_path}`'s fix-scope hint when injected — takes priority.
2. Else, on a `{failing_result}`, its `stage_specific` fields (per that stage's result schema).
3. Else, if `{workdir}/changed-inputs.md` is present, it lists the input files that changed since
   this stage's last run — confine the env-build child's edits to what it implies. **Scope
   discipline:** when `changed-inputs.md` shows only RTL changed and the plan did not drift, the
   testbench is out of scope — preserve it byte-for-byte; conformance re-judges regardless, so
   correctness never rests on this.
4. Else (a first delivery, no prior canonical) the full TB — fill every rendered `TODO(`.

**Workdir on entry.** `{workdir}` may already hold your previous round's carried TB (rework —
`carry_self` ran before you were dispatched) or be genuinely empty (first run); either way the
caller hands you the same directory to dispatch env-build into. The `bootstrap` verb (Step 2) is
no-clobber: it deploys the template only where a file is missing, so a carried TB is never
overwritten and a first run gets the complete pristine template.

**Internal scripts.** The `bootstrap` verb performs the rtl_filelist rewrite + scaffold render in-process (the former three-script pipeline collapsed into one verb); the standalone re-render entry is `sim render-scaffold`. The deployed `infra/scripts/` (`run_vcs_regression.sh` /
`parse_coverage.py` / `write_summary.py`) are make-internal. The interfaces are
the `bootstrap` verb and the `make` targets (`simv` / `smoke` / `regress` / `coverage` /
`summary`) — none of these internal scripts is invoked or read directly.

### Step 2: Wave 1 — dispatch env-build

Dispatch one `Task(run_in_background=True)` — the env-build child — whose prompt points to
[`references/env-task-contract.md`](references/env-task-contract.md) and hands over paths only
(`{workdir}`, `{module}`, the scaffold-spec path, the verification-plan path, and Step 1's resolved
scope — whichever of `{failing_result}` / `{directive_path}` / the `changed-inputs.md` change-set
applied).

The env-build child self-gates its `STATUS: DONE` on a presence-only thin-D1 check
(`sim check-materialization`: no surviving TODO, all required scaffold files present) so a
hollow TB never reaches the Wave-3 verify run; semantic TB↔plan conformance is out of scope for this
presence-only check (it is the conformance gate's job).

After dispatching, end the turn and wait for the harness wake.
On wake-up, reap the env-build child's harness `STATUS:` last line + its JSON line. If
`STATUS: BLOCKED <reason>`, run `sim finalize --workdir {workdir} --module <module>
--phase env-blocked --failure-phase <compile|smoke|prerequisite> --fail-reason "<reason>"`
(`--failure-phase` per the reason — `compile` / `smoke` for a Rule A semantic block, `prerequisite`
for an incomplete `inlined_check_hints[]` block) and return; do not dispatch the downstream waves.

### Step 3: Smoke gate (deterministic; main thread)

Gate on the smoke result emitted by the smoke run's own tooling in `{workdir}`, NOT on the
env-build child's self-reported `STATUS:` prose. This is cheap and deterministic — the main thread
reads a small status file and does NOT re-run heavy EDA. Do NOT use
the `sim` exit gate here — its coverage gate hard-fails pre-regress (no `structural-coverage.json`
exists yet).

- **Compile failed (no smoke status):** `make simv` produced no `simv`, so `make smoke` ran no test
  and `regression-log.txt` carries no `RESULT` line. Run `sim finalize --phase smoke
  --failure-phase compile --fail-reason "<…>"`; skip the downstream waves.
- **Smoke ran but failed:** `regression-log.txt`'s `RESULT <test> <PASS|FAIL|MANUAL_REVIEW>` lines (or
  the per-test `logs/<test>.status` files) contain any non-`PASS`. Run `sim finalize
  --phase smoke --failure-phase smoke --fail-reason "<…>"` (pass `--verify-verdict <reaped, carries
  failing_cases>`); skip the downstream waves.
- **Smoke passed:** every `RESULT` line is `PASS` → proceed to Step 4 (conformance gate).

### Step 4: Wave 2 — conformance gate (LLM check-adequacy review; gating)

**Re-judged every round — never skipped.** `conformance-review.json` is deliberately never carried
forward (the framework's `carry_self` excludes it), so there is no stale prior verdict to reuse: on
every smoke pass, dispatch the conformance reviewer and gate on its fresh finding set, whether or
not the testbench itself changed this round.

On a smoke pass, dispatch one `Task(run_in_background=True)` — the conformance reviewer —
whose prompt points to [`references/conformance-review-task-contract.md`](references/conformance-review-task-contract.md)
and hands over paths only: the `{workdir}` (filled `tb/uvm/**`), the scaffold-spec path
(`testpoints[].inlined_check_hints[]`), the `verification-plan.md` path (§3 intent source),
the DUT RTL filelist, and `{module}`. After dispatching, end the turn and wait for the harness wake.

On wake-up, reap the reviewer's `STATUS:` last line + its JSON line, assemble
`{workdir}/conformance-review.json` (schema `references/conformance-review.schema.json`), and run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py validate-review --review {workdir}/conformance-review.json
```

On a non-zero exit, re-assemble the JSON and re-run (this is a main-thread fix, NOT a re-dispatch).
On exit 0 it prints a one-line gate verdict `{"gate": "trip"|"clear", "flagged": [...],
"dominant_category": ...}` — the mechanical category × severity reduction (per the reviewer
contract's "Severity & gating"), computed by the script, not judged by eye. Apply it:

- **`gate=trip`:** disposition the gating findings by category (the `conformance_findings` subset
  `compute_gate` identifies — category ∈ {`missing`, `wrong-behavior`, `fake-green`, `intent-defect`}
  at `critical`/`important`; the gate verdict's `flagged` list carries only `tp_id`s, so read each
  gating finding's category from `conformance-review.json`'s `findings[]`):
  - **self-locus** (`missing` / `wrong-behavior` / `fake-green` — the check itself is inadequate, and
    this stage owns the check) **→ self-heal loop in-stage** (mirroring rtl-design's self-converge):
    dispatch one conformance-fix `Task(run_in_background=True)` per
    [`references/conformance-fix-task-contract.md`](references/conformance-fix-task-contract.md),
    injecting the self-locus gating findings (`tp_id` / `category` / `location` from
    `conformance-review.json`) as fix-scope; on wake, **re-run this Step-4 conformance reviewer
    wave** ([`references/conformance-review-task-contract.md`](references/conformance-review-task-contract.md))
    and re-apply the verdict. There is no build step in this loop — the reviewer is a static
    check-adequacy review; a compile-breaking fix surfaces at the Step-5 verify wave. **Exit:** the
    re-run gate reaches `clear` (converged → proceed to Step 5) or the conformance-fix Task returns
    `STATUS: BLOCKED` (it judges the defect is a plan/intent gap beyond the check implementation) →
    fail-out via the `intent-defect` path below. **No round cap** (exit is fixer-BLOCKED /
    convergence). The fix Task only tightens `tb/uvm/**` check logic — `verification-plan.md` /
    `scaffold-specification.json` are the read-only intent source (Iron Rule), and a check is never
    loosened to pass the gate.
  - **upstream** (`intent-defect` — the testpoint intent itself is wrong; no check change can fix
    it) **→ fail-out** (unchanged): run `sim finalize --workdir {workdir} --module <module> --phase
    conformance --fail-reason "<built from flagged + dominant_category>" --conformance-review
    {workdir}/conformance-review.json` (finalize re-derives the gating `conformance_findings` subset
    in-process via `compute_gate`, carried to triage as `failure_signal`, and enumerates
    `conformance-review.json` in `artifacts[]`); **skip Step 5** (do not dispatch the verify wave).
    The existing `failure_phase=conformance` → simulation-triage → route path applies (triage
    supplies the confidence, so no in-skill confidence gate is needed here).
  - **both present** → self-heal the self-locus findings first; any `intent-defect` finding
    remaining after convergence then fails out per the upstream rule.
- **`gate=clear`:** proceed to Step 5. Advisory findings (`unverifiable-arch` any severity, `minor`,
  `unavailable`) never trip the gate — record them in `conformance-review.json` and surface a
  `⚠ <tp> <category>` line in the completion summary.
- **Review unavailable** (`STATUS: BLOCKED`, malformed/unparseable JSON, or any dispatch/reap/
  aggregate/validate error) → **do NOT gate**: still write a minimal `conformance-review.json`
  `{... "findings":[{"tp_id":"-","severity":"minor","category":"unavailable","location":"-","summary":"review (wave) failed: <reason>"}]}`
  (so the absence of a real review is a first-class artifact, not invisible; the validator reports
  `gate=clear` for it), note it in the completion summary, and proceed to Step 5.
- **Verdict integrity:** you MUST NOT override a `gate=trip` to pass.

A self-locus conformance defect self-heals in-stage (above); only an `intent-defect` trip — or a
conformance-fix Task that `BLOCKED`s — takes the fail-out to the existing
`failure_phase=conformance` → simulation-triage → route path.

### Step 5: Wave 3 — dispatch verify

Dispatch one `Task(run_in_background=True)` — the verify child — whose prompt points to
[`references/verify-task-contract.md`](references/verify-task-contract.md) and hands over the same
`{workdir}` (already holding the built TB + compiled `simv` + `verify-handoff.json`), the
scaffold-spec testpoints path, and `{module}`.

After dispatching, end the turn and wait for the harness wake.
On wake-up, reap the verify child's `STATUS:` last line + its JSON line (the `stage_specific` fields),
then branch on its verdict and write `status=fail` via finalize, **skipping Step 6** (do NOT call
`--phase final`):

- a `make regress` case failed → `sim finalize --phase regress --failure-phase regress
  --fail-reason "<…>" --verify-verdict <reaped, carries failing_cases>
  --scaffold <scaffold>/scaffold-specification.json`;
- Rule-B uncovered bins (`failure_phase=coverage` from the verify child) → `sim finalize
  --phase regress --failure-phase coverage --fail-reason "<…>" --verify-verdict <reaped,
  carries coverage_gaps + gaps_not_in_testpoints ∨ gaps_in_testpoints>
  --scaffold <scaffold>/scaffold-specification.json`;
- `STATUS: BLOCKED <reason>` → `sim finalize --phase verify-blocked --fail-reason
  "verify child BLOCKED: <reason>"`.

Only a **clean** verify verdict (no `failure_phase`, not BLOCKED) proceeds to Step 6.

### Step 6: Finalize + write `{workdir}/result.json` (script)

On a clean verify pass, run the finalize subcommand; do not hand-assemble the envelope, re-derive
counts, or copy gate verdicts by hand. Pass the scaffold-spec + thresholds it reuses for the
compile/coverage gate, the assembled `conformance-review.json`, and the reaped verify-child verdict
(carrying `stimulus_iterations`):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py finalize \
  --workdir {workdir} --module <module> --phase final \
  --scaffold <scaffold>/scaffold-specification.json \
  --thresholds ${CLAUDE_SKILL_DIR}/defaults.yaml \
  --conformance-review {workdir}/conformance-review.json \
  --verify-verdict {workdir}/<reaped-verify-verdict>.json
```

`finalize` enumerates `conformance-review.json` + `verify-handoff.json` in `artifacts[]` automatically
via `enumerate_artifacts` — both are written fresh every round (Step 4 / Step 2), never carried.

`finalize --phase final` reuses the host's own `thin_d1` + `coverage_gate` in-process for the
exit-code gate (thin-D1 fail → `failure_phase=compile`, coverage fail → `failure_phase=coverage`,
earlier phase wins), derives the informational pass-summary (`total_cases`/`passed`/`failed` from
`coverage-summary.txt`, `coverage_summary` from `structural-coverage.json.aggregate`,
`conformance_gate` + `conformance_advisory[]` from `conformance-review.json` with each advisory `note`
copied verbatim from the finding `summary`, `stimulus_iterations` from the reaped verify verdict),
enumerates `artifacts[]`, and writes the complete `result.json`. Exit 0 = result.json written (status
pass or fail). A non-zero finalize exit is a program exception (BLOCKED), not a `status=fail`.

**Verdict integrity (anti-gaming):** you MUST NOT override any gate's fail to pass.
`status=pass` is written by finalize only on `--phase final` when `thin_d1`/`coverage_gate` are clean
and no upstream gate — smoke, conformance, **or the Step-5 verify wave** (`regress` / Rule-B `coverage` /
`verify-blocked`) — routed out (each of those wrote its own `status=fail` via its own `--phase` call and
skipped the downstream waves; so a regression/coverage/blocked failure can never reach the
compile/coverage-only `--phase final` and be mis-written as pass). This mirrors rtl-design's child-status
precedence: you record the most-failing verdict, never a more-optimistic one.

The `failure_phase` value table below documents which step decides each phase; finalize owns the
`compile`/`coverage` finalize rows and writes the rest via `--phase`. `failure_phase` is required when
`status=fail`; `fail_reason` (one-line summary) is required on every fail path; both are absent on pass.

| failure_phase | First-failing phase | Companion fields (besides `fail_reason`) | Decided in |
|---|---|---|---|
| `prerequisite` | Step 1 reference missing, or `{failing_result}` unreadable; or env-build `STATUS: BLOCKED` for incomplete `inlined_check_hints[]` | — | main thread |
| `compile` | `make simv` failed (no smoke status); or `sim finalize` thin-D1 file missing / `TODO(` residue | — | smoke gate (Step 3) / finalize (Step 6) |
| `smoke` | `make smoke` ran but a `RESULT` line is not `PASS` | `failing_cases` | smoke gate (Step 3) |
| `conformance` | Conformance gate (Step 4): a finding `category ∈ {missing,wrong-behavior,fake-green,intent-defect}` at `critical`/`important` | `conformance_findings` | conformance gate (Step 4) |
| `regress` | Any case fails in `make regress` | `failing_cases` | verify child |
| `coverage` | Rule-B uncovered bins, or `sim finalize` coverage gate (dim below threshold / not extractable) | `coverage_gaps` + `gaps_not_in_testpoints` or `gaps_in_testpoints` (Rule B); `coverage_extractable` + `dims` (sim finalize) | verify child / finalize (Step 6) |

## Decision Rules

The detailed Rule A / Rule B authority lives with the sub-Task that owns it:

- **Rule A (scaffold vs semantics):** env phase — compile/smoke scaffold-repair budget. See
  [`references/repair-boundaries.md`](references/repair-boundaries.md) and
  [`references/env-task-contract.md`](references/env-task-contract.md).
- **Rule B (stimulus vs intent):** verify phase — coverage stimulus iterate. See
  [`references/coverage-iteration.md`](references/coverage-iteration.md) and
  [`references/verify-task-contract.md`](references/verify-task-contract.md).
- Regress fail → the verify child does not modify checker / scoreboard / RM; it writes
  `failing_cases` and routes out for the caller to decide.

The cycle-accurate check-authoring + anti-gaming rules (the `inlined_check_hints[]` handling) live in
[`references/inlined-check-hints.md`](references/inlined-check-hints.md), cited by the env-build
sub-Task.

## Red Flags

| Excuse | Reality |
|---|---|
| "The verify child's counts look fine — I'll write `status=pass`" (when a gate tripped or `sim finalize` exited non-zero) | You record the most-failing verdict, never a more-optimistic one. `status=pass` is written only when the smoke gate, the conformance gate, the verify verdict, and `sim finalize` all agree (Step 6); you MUST NOT override a `gate=trip` to pass (Step 4). |
| "The env-build child's `STATUS:` line says smoke passed — that's my smoke gate" | The smoke gate reads the smoke run's own tooling (`regression-log.txt` `RESULT` lines / per-test `logs/<test>.status`), never the child's self-reported prose (Step 3). |
| "A case is failing — I'll open the TB to see why" | The main thread NEVER reads the TB body or re-runs heavy EDA; it consumes envelopes / status files / paths only and routes the failure out for the caller to decide (Iron Rule). |
| "I'll peek at the DUT RTL to write the refmodel for this signal" | The TB's golden model derives from the sim-plan docs only; a model read off the RTL mirrors it and verifies nothing (circular). Author from `implementation_detail` / §3 intent; if insufficient, BLOCK to simulation-plan (Iron Rule). |

## Completion Gate (main thread)

- [ ] No Iron Rule was triggered.
- [ ] Every round ran the same homogeneous sequence — no branch was taken; Step 2's env-build child
      was dispatched unconditionally, and Step 1's edit scope (directive / `{failing_result}` /
      `changed-inputs.md`) was resolved and handed to it.
- [ ] The smoke gate (Step 3) was evaluated against the smoke run's own status (`regression-log.txt`
      `RESULT` lines / per-test `.status`), not the child's prose; the verify wave was dispatched only
      on a smoke pass.
- [ ] On a smoke pass, the conformance reviewer (Step 4) was dispatched and reaped **every round,
      never skipped** — `conformance-review.json` was written fresh + schema-validated; the verify
      wave was dispatched only when the gate did not trip (or a review-unavailable fall-through).
- [ ] On a smoke pass, the verify sub-Task was dispatched and reaped.
- [ ] `result.json` was written by `sim finalize` (it reuses `thin_d1`/`coverage_gate`
      for the exit-code gate and owns status / failure_phase / the pass-summary / artifacts[]; every
      exit path calls it via `--phase`).

## Return Contract

Main-thread skill: control returns directly to the caller; the caller decides based on
`{workdir}/result.json` (`status ∈ {pass, fail}`). There is no Task-subagent `STATUS:` last-line
signal from this skill itself.

Each dispatched sub-Task ends with a harness-level `STATUS: DONE` + a single JSON line, or
`STATUS: BLOCKED <reason>` (schemas in `references/env-task-contract.md` /
`references/verify-task-contract.md`). These signals are consumed by the simulation main thread
(reaped into the gate + the `result.json` assembly), not by the caller.

## Bundled References

- [`references/env-task-contract.md`](references/env-task-contract.md) — Wave-1 env-build sub-Task contract (bootstrap + fill + compile + smoke; defines `verify-handoff.json`).
- [`references/conformance-review-task-contract.md`](references/conformance-review-task-contract.md) — Step 4 (Wave 2) conformance reviewer sub-Task contract (gating; check-adequacy intent review).
- [`references/conformance-review.schema.json`](references/conformance-review.schema.json) — schema for `conformance-review.json` (the gate source).
- [`references/verify-task-contract.md`](references/verify-task-contract.md) — Wave-3 verify sub-Task contract (regress + coverage iterate + summary).
- [`references/inlined-check-hints.md`](references/inlined-check-hints.md) — cycle-accurate check authoring + anti-gaming rules (cited by env-build).
- [`references/artifact-contract.md`](references/artifact-contract.md) — simulation artifact contract, split by owning phase.
- [`references/repair-boundaries.md`](references/repair-boundaries.md) — Rule A: scaffold vs. semantic repair boundary (env phase).
- [`references/coverage-iteration.md`](references/coverage-iteration.md) — Rule B: stimulus vs. intent coverage classification (verify phase).
- [`references/uvm-rules.md`](references/uvm-rules.md) — UVM coding rules.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
