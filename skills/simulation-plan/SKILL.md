---
name: simulation-plan
description: Use when generating or evolving the verification plan, scaffold specification, testpoints, and power scenarios for a module; not for materializing UVM TB or running EDA tools.
---

# Verification Planning

Your sole responsibility: from `specification`, produce `verification-plan.md` — the human-readable
review anchor — plus its machine half, three sidecars split so each downstream consumer declares
only what it reads.

## Iron Rule

- Write only under `{workdir}`; never another module's artifacts.
- Do not read RTL source, do not invoke EDA tools. A plan written from the implementation verifies
  the implementation against itself.

## Artifacts

Read `{workdir}/dispatch.json` for this round's inputs: its `inputs` table maps each upstream key
to a location, so `<key>/<subpath>` is how you address one. `design` / `manifest` / `children` /
`clocks` / `features` / `check_hints` / `top_io` all resolve to the specification stage root.

| Path | What it is |
|---|---|
| `<design>/design.md` | §1 behavior, §1.4 boundary, and §1.5 timing scenarios with their waveforms — the only home for the scenarios you author sequences from, so you read it |
| `<children>/<child>.md` | Per-child implementation constraints a testpoint may have to verify: register side effects, exceptions, concurrency, back-pressure, reset, state-machine boundaries |
| `<design>/features.json` | The feature list you author testpoints and tests from |
| `<design>/check-hints/<child>.json × N` | Per child, the checks that verify it — `check_id` is unique across all of them |
| `<design>/clocks.json`, `<design>/top-io.json` | The clock and the DUT boundary `materialize-scaffold` derives from |
| `<manifest>/manifest.json` | `.module` is the Top field in plan §1; `children[]` is the roster the check hints are aggregated over |

Everything below is produced under `{workdir}`.

| Path | What it is |
|---|---|
| `verification-plan.md` | The review anchor the Step-4 gate is held over (section outline below) |
| `tb-scaffold.json` | What simulation builds the TB from: `agents` / `tests` / `testpoints[]` / `rm` / `scoreboard` / `skipped_checks[]` |
| `sequences.json` | The sequence roster — the one part both simulation and power-analysis read |
| `power-scenarios.json` | The power scenarios, read by power-analysis alone. Its own file so a scenario-only edit does not invalidate simulation's proof |
| `plan-review/review.md`, `plan-review/decisions.md` | The Step-3 review and the user's resolutions — this stage's proposed oracle |
| `result.json` | The status envelope, written only by `finalize` |

Each sidecar's shape, and per field whether it is yours to author or script-injected, is
[`references/tb-scaffold.schema.json`](references/tb-scaffold.schema.json) /
[`sequences.schema.json`](references/sequences.schema.json) /
[`power-scenarios.schema.json`](references/power-scenarios.schema.json). Read them before authoring:
they carry the judgment no validator can express, and `simplan check-scaffold` enforces the rest.

### `verification-plan.md` section outline

```markdown
# <module> Verification Plan

## 1. Scope
Module name / Top / spec references.

## 2. Test Strategy
Agent grouping / sequence design / RM type / scoreboard boundary — as narrative. The rosters
themselves live in the sidecars; write why each boundary falls where it does, not a table of the
fields you just authored there.

## 3. Testpoints
The testpoints live in `tb-scaffold.json`'s `testpoints[]`. Do not restate them as a table.
Narrative that is not a per-testpoint field belongs here: how the testpoints partition the
verification, which behaviors are deliberately left to downstream stages.

## 4. Power Scenarios
One materialization note per scenario, per `references/power-scenarios-template.md`: the standard
row's abstract states, what they reduce to on this module, and why a row was materialized that way
or dropped as inapplicable. `power-scenarios.json` carries only the four fields power-analysis
reads, so this section is the sole home for everything else about a scenario.

## 5. Revision Summary (append on a scoped revision when a real diff is present)
Trigger context + revision highlights.

## Document Control
```

## Workflow

### Step 1: Read inputs, determine scope

Your previous round, if any, is already in `{workdir}`; edit it in place, touching only what this
round requires. Rewriting an artifact this round did not change changes its fingerprint, which
drops any human `pin` on it back to `proposed` — the next signature would land on text nobody
reviewed. Confirm `<design>/design.md` + `<manifest>/manifest.json` exist; if a required input is
missing, close the run with the early-fail exit below
(`fail_reason="external reference missing: <path>"`).

The kernel writes `scope` / `caused_by` / `reasons` into `dispatch.json` **only when they carry
something**, so their presence is what tells you which kind of round this is. Either way you run
Steps 2–5; the branch decides how much of the plan you touch.

- **`caused_by` present:** a repair round. Scope is the union of `dispatch.json`'s `scope` — the
  module-relative paths or `<file>:<line>` anchors whose change invalidated the plan — and what the
  `caused_by` envelopes attribute; read each envelope once, and amend only the plan sections those
  paths map to. It is a pointer, not a boundary: if the gap sits elsewhere, widen and record why in
  `result.json`. `reasons`, when present, is a human's judgment on this repair and outranks your own
  reading of the files.
- **`caused_by` absent:** a first delivery — generate the plan and all three sidecars. If
  `{workdir}` already holds a partial round, the session was compacted or interrupted: that work is
  yours to continue or redo, and artifacts on disk are not a gate you already passed.

**Early-fail exit.** Whenever a documented failure cannot be resolved, close the run with the
finalize early-fail entry, not a hand-assembled envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --module {module} --spec <design> \
  --status fail --fail-reason "<one-line reason>" [--fix-owner <rule>]
```

`--fix-owner` names the rule that must act. A gap you cannot cover because the spec does not say
enough is `specification`. A gap that is yours to close is yours to close in this round, so naming
yourself means the plan cannot be made adequate from here and a human should look. Omit it when you
cannot tell.

### Step 2: Generate / update artifacts

Author the judgment fields into the three sidecars and write `verification-plan.md` per the section
outline. How the spec fields map to the scaffold objects — agents from interface groups, sequences
from §1.5 scenarios, tests from features, RM / scoreboard from the check hints — is
[`references/spec-input-contract.md`](references/spec-input-contract.md).

Every `check_hints[]` check_id must end up in some `testpoints[].covers[]` or in `skipped_checks[]`
with a reason; the gate below enforces the matrix, so it is not a judgment you can rationalize
past. Power scenarios come from
[`references/power-scenarios-template.md`](references/power-scenarios-template.md) — load the table
before authoring, because no gate checks that a scenario came from the standard set. Every
`sequence_ref` must resolve to a `sequences[].name`; add the `sequences[]` entry first when a
scenario needs its own stimulus.

When amending, keep testpoint IDs / sequence names / `sequence_ref` stable: downstream coverage /
scaffold / SAIF caches key off them, so renumbering one silently breaks the cache. One amendment is
counter-intuitive enough to name: when triage attributes a coverage hole to plan over-spec — a bin
the RTL cannot legally reach — **narrow** `bins` rather than chasing the hole, and delete the
testpoint outright if the whole thing is unreachable, recording the over-spec attribution in §5.
Coverage does not fall; a bin that could never be hit was never coverage.

**Run `materialize-scaffold`** (every run) to fill the script-injected fields:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py materialize-scaffold --plan {workdir} --spec <design>
```

On a non-zero exit, read stderr for the cause, fix the scaffold or (for a clock defect) re-run
specification — `clocks.json` is its output, not yours — and re-run.

**Run `check-scaffold`** (the gate; every pass) to validate the sidecars' structure, semantics, and
coverage matrix:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py check-scaffold --plan {workdir} --spec <design>
```

Fix and re-run on a non-zero exit.

### Step 3: Plan-adequacy review

On every run, dispatch ONE Level-1 reviewer per
[`references/plan-review-task-contract.md`](references/plan-review-task-contract.md), passing
paths. It writes its own `{workdir}/plan-review/review.md`; you read no body and re-type nothing.
After dispatching, send a brief status and end the turn; reap before proceeding.

A `STATUS: BLOCKED` reviewer is a crash, not a verdict: the review did not happen, so close the run
via the early-fail exit with that as the reason rather than recording a review that did not run. An
absent `plan-review/review.md` also leaves the oracle unreadable, so `signoff` could not pin this
stage anyway.

### Step 4: User review loop (human)

Path-handoff — present the `verification-plan.md` path and the `plan-review/review.md` path,
echoing no body.

You do not summarize the findings, rank them, or decide which ones matter: a review relayed through
your summary is your judgment wearing the reviewer's name.

Then the user approves, requests changes, or rejects:

- **approve**: if the user accepts a finding the reviewer called blocking, write their reason —
  **their words, not yours** — to `{workdir}/plan-review/decisions.md`. It is promoted with the
  review, so what the user endorsed over the reviewer's objection, and why, is what `signoff` later
  pins. Nothing downstream re-checks testpoint-vs-spec (sim conformance judges TB-vs-testpoint), so
  an accepted coverage gap is a terminal accept.
- **request changes**: revise incrementally (return to Step 2), re-run Step 3, re-present.
- **reject**: close the run with the Step-5 finalize, passing `--status fail` (it writes
  `fail_reason="user rejected plan"`).

### Step 5: Finalize (script, mandatory)

Run finalize to write the stage's `result.json`; never hand-assemble the envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --module {module} --spec <design> \
  [--status fail] [--fail-reason "<one-line reason>"] \
  [--revision '<one-line revision narrative>']
```

You supply only the human-gate outcome: on a fail `--status fail` (with `--fail-reason` for a
Step-1 early-fail; without, the user reject), and `--revision` on a scoped revision. finalize
re-runs `check-scaffold` in-process — it was clean at Step 2, so a failure now means an artifact was
edited after the gate: BLOCKED, not a routable fail. It does not re-judge the review; that is prose
under `plan-review/`, promoted and fingerprinted as this stage's proposed oracle. Exit 0 =
`result.json` written (status pass or fail); a non-zero exit is a program exception (BLOCKED, reason
on stderr), not a `status=fail`.

## Return Contract

Control returns to the caller, which decides what runs next from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is
incomplete (no cross-session "already complete" flag), so a repair round or a compaction resume
just re-enters and re-runs the pipeline idempotently.
