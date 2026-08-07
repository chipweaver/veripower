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
| `verification-plan.md` | The review anchor the human gate is held over (template: `references/verification-plan-template.md`) |
| `tb-scaffold.json` | What simulation builds the TB from: `agents` / `tests` / `testpoints[]` / `rm` / `scoreboard` / `skipped_checks[]` |
| `sequences.json` | The sequence roster — the one part both simulation and power-analysis read |
| `power-scenarios.json` | The power scenarios, read by power-analysis alone. Its own file so a scenario-only edit does not invalidate simulation's proof |
| `plan-review/review.md`, `plan-review/decisions.md` | The reviewer's findings, and the user's resolution of anything it called blocking |
| `result.json` | The status envelope |

Each sidecar's shape, and per field whether it is yours to author or script-injected, is
[`references/tb-scaffold.schema.json`](references/tb-scaffold.schema.json) /
[`sequences.schema.json`](references/sequences.schema.json) /
[`power-scenarios.schema.json`](references/power-scenarios.schema.json). Read them before authoring:
they carry the judgment no validator can express, and `simplan check-scaffold` enforces the rest.

## Workflow

Two phases, each closed by its own gate, then finalize.

### Which round is this

The kernel writes `scope` / `caused_by` / `reasons` into `dispatch.json` **only when they carry
something**, so their presence is what tells you. Either way you run both phases; the branch
decides how much of the plan you touch.

- **`caused_by` present — failures are waiting on this stage.** Each entry is one failing run's own `result.json`, and a round scheduled for some other reason carries them too: answer them in this round. Scope is the union of `dispatch.json`'s `scope` — the
  module-relative paths or `<file>:<line>` anchors whose change invalidated the plan — and what the
  `caused_by` envelopes attribute; read each envelope once, and amend only the plan sections those
  paths map to. It is a pointer, not a boundary: if the gap sits elsewhere, widen and record why in
  `result.json`. `reasons`, when present, is a human's judgment on this repair and outranks your own
  reading of the files.
- **`caused_by` absent — a first delivery.** Generate the plan and all three sidecars.

Your previous round, if any, is already in `{workdir}`: edit it in place, touching only what this
round requires. Rewriting a sidecar this round did not change still changes its bytes, and
`simulation` and `power-analysis` both declare those files as inputs, so a cosmetic rewrite costs a
full TB recompile and regression downstream for no change in content.

A `{workdir}` already holding part of a round means the session was compacted or interrupted: that
work is yours to continue or redo, and artifacts on disk are not a gate you already passed.

### Author the plan and its sidecars

Author the judgment fields into the three sidecars and write `verification-plan.md` per
[`references/verification-plan-template.md`](references/verification-plan-template.md). How the spec
fields map to the scaffold objects — agents from interface groups, sequences from §1.5 scenarios,
tests from features, RM / scoreboard from the check hints — is
[`references/spec-input-contract.md`](references/spec-input-contract.md).

Every `check_hints[]` check_id must end up in some `testpoints[].covers[]` or in `skipped_checks[]`
with a reason; the gate below enforces that matrix. Power scenarios come from
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

**Gate, script.** Run `materialize-scaffold` to fill the script-injected fields, then
`check-scaffold` to validate the sidecars' structure, semantics, and coverage matrix:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py materialize-scaffold --plan {workdir} --spec <design>
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py check-scaffold --plan {workdir} --spec <design>
```

Both run on every pass. Each names the defect on stderr; `materialize-scaffold` also names the
upstream stage to re-run when what is missing is the spec's. Fix and re-run until clean, or finalize
a failure when the defect is not yours to fix.

### Review the plan

Dispatch ONE Level-1 reviewer per
[`references/plan-review-task-contract.md`](references/plan-review-task-contract.md), passing paths.
It writes its own `{workdir}/plan-review/review.md`. After dispatching, send a brief status and end
the turn; reap before proceeding. A `STATUS: BLOCKED` reviewer is a crash, not a verdict: the review
did not happen, so finalize a failure with that as the reason.

**Gate, human.** Path-handoff: present the `verification-plan.md` path and the
`plan-review/review.md` path, echoing no body.

You do not summarize the findings, rank them, or decide which ones matter: a review relayed through
your summary is your judgment wearing the reviewer's name.

Then the user approves, requests changes, or rejects:

- **approve**: if the user accepts a finding the reviewer called blocking, write their reason —
  **their words, not yours** — to `{workdir}/plan-review/decisions.md`, so the override travels
  with the review it overrode instead of living only in this session. Nothing downstream re-checks
  testpoint-vs-spec (sim conformance judges TB-vs-testpoint), so an accepted coverage gap is a
  terminal accept.
- **request changes**: revise incrementally, re-run the script gate, re-dispatch the reviewer,
  re-present.
- **reject**: finalize with `--status fail` and no `--fail-reason`, which records
  `fail_reason="user rejected plan"`.

### Finalize

Every run ends here, including one you could not carry to the human gate:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --spec <design> \
  [--status fail] [--fail-reason "<one-line reason>"] [--fix-owner <rule>] \
  [--revision '<one-line revision narrative>']
```

You supply only the human-gate outcome, plus `--revision` on a scoped revision. On a failure name
the owner: `--fix-owner specification` when the spec does not say enough for any plan to cover the
gap, `--fix-owner simulation-plan` when the gap is yours but you have exhausted what you can do
from here, and omit the flag when you cannot tell.

finalize re-runs `check-scaffold` in-process on the pass path — it was clean at the script gate, so
a failure now means an artifact was edited afterwards, which is BLOCKED rather than a routable fail.
Exit 0 = `result.json` written, status pass or fail. A non-zero exit is a program exception:
BLOCKED, reason on stderr, never a `status=fail`.

## Return Contract

Control returns to the caller, which decides what runs next from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`.
