---
name: simulation-plan
description: Use when generating or evolving the verification plan, scaffold specification, testpoints, and power scenarios for a module; not for materializing UVM TB or running EDA tools.
---

# Verification Planning

Your sole responsibility: from `specification`, generate or evolve two artifacts — `verification-plan.md` (human-readable review anchor, with a testpoints section and a power-scenarios section) and `scaffold-specification.json` (machine-read contract, with `agents` / `sequences` / `tests` / `testpoints[]` / `power_scenarios[]`). **Do not read RTL source; do not invoke EDA tools.**

## When to Use

- First-time generation of plan + scaffold spec for a module.
- A repair round after a `specification` change — amend the plan/scaffold incrementally.
- Plan / scaffold revisions from review feedback.

## Iron Rule

Your boundary:

- **Do not modify any file outside this run's workspace.** Only write artifacts under `{workdir}` and `result.json`.
- **Do not read RTL source, do not invoke EDA tools, and do not write `tb/uvm/` / `Makefile` / `vcd/`.** These belong to the TB-materialization stage.
- **Minimal edit on any re-dispatch with a prior valid `verification-plan.md` / `scaffold-specification.json` on disk.** Edit only the sections this round's task requires (scope is determined in Step 1); every section outside that scope MUST stay byte-identical to the prior run.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Fan-out Dispatch Contract

- **One Level-1 review sub-Task only:** dispatches the Step-4 plan-adequacy reviewer via
  `Task(run_in_background=True)`, reaps it, and folds the result into `plan-review.json`
  (Level-2 forbidden — the audit boundary).
- **Dispatch-and-wait:** after dispatching, end the turn; reap on the harness wake; aggregate the
  reviewer's report and proceed only after it reports (DONE or BLOCKED).
- **No `kernel.py`:** this skill does not call `kernel.py`.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{failing_result}` | Optional. The failed stage's canonical `result.json` path (field names per that stage's schema); when present, supplies this round's fix scope (Step 1). |
| `{directive_path}` | Optional. Fix-scope hint file; Read it first — priority over the trigger's attribution fields. |

### External reference inputs

| Path | Schema / Format | Use |
|---|---|---|
| `Design/specification/result.json` | `skills/specification/references/result.schema.json` | `specification` envelope — existence-checked at Step 1. You do not consume `ppa_targets`. |
| `Design/specification/design.md` | Custom markdown | Module-level design (§1.1–1.6: features / IO / interconnects / timing scenarios / clocks). Per-submodule content lives in each `<child>.md`. |
| `Design/specification/manifest.json` | Custom JSON (specification child registry) | `.module` fills the Top field in plan §1 Scope; child roster — drives per-child `§5` consumption by `simplan derive-plan-data`. |
| `Design/specification/<child>.md × N` | Custom markdown | Only `§5 Verification Hints` is consumed (via `simplan derive-plan-data`, tagging `check_hints[]` with `child`). |

When `{failing_result}` is injected, read additional context from the same directory as the trigger file (e.g., `failure_phase` / `failing_cases` / `coverage_gaps` / `gaps_not_in_testpoints` / `failures[]` / corresponding log and summary files). The specific read scope is driven by the trigger's content; do not enumerate it ahead of time.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `verification-plan.md` | Custom markdown (section outline below); after the review loop carries frontmatter `Status: approved` | Human-readable review anchor — drives the Step-5 user loop. |
| `scaffold-specification.json` | Custom JSON (field convention below); written after the Plan Gate | Machine-read contract (drives TB-materialization bootstrap + scaffold generation). |
| `plan-review.json` | `references/plan-review.schema.json` | Gating plan-adequacy review (Step 4 aggregate); promoted — the resume-guard re-reads the promoted copy. |
| `plan-data.json` | Custom JSON (derived by `simplan derive-plan-data`) | Intermediate cache, re-derived on every Step-3 pass; **not** placed in `result.json.artifacts[]`. |

The promoted full set is enumerated by `simplan finalize` — this table is the contract surface, not a mirror of it.

### `verification-plan.md` section outline

```markdown
# <module> Verification Plan

## 1. Scope
Module name / Top / spec references.

## 2. Test Strategy
Agent grouping / sequence design / RM type / scoreboard boundary.

## 3. Testpoints Table
| TestpointID | FeatureID | Bins | Class | Suites | Stimulus / Intent | CoverageIntent |
| ... | ... | ... | ... | ... | ... | ... |

## 4. Power Scenarios Materialization
(Materialize each scenario per `references/power-scenarios-template.md`: reset sequence name / business_flow / low-power signals / DVFS frequency bands; equivalent scenarios share `sequence_ref` but keep independent IDs and `corner_intent`.)

## 5. Revision Summary (append on a scoped revision when a real diff is present)
Trigger context + revision highlights.

## Document Control
```

### `scaffold-specification.json` fields

You author (judgment): `module`, `top`, `agents[]` `{name, mode, interface_groups}`,
`sequences[]`, `tests[]`, `rm`, `scoreboard`, `testpoints[]` `{id, bins, intent, covers}`,
`power_scenarios[]`, and `skipped_checks[]` `{check_id, reason}`.

Script-injected by `simplan materialize-scaffold` (do NOT hand-author): each agent's
`interface.signals` (all group signals) + `transaction.fields` (clk/rst excluded), `primary_clock`, `reset`, and each
`testpoints[].inlined_check_hints[]` (materialized from `covers[]` + plan-data,
`implementation_detail = verbatim-if-present-else-summary`).

Full structural shape: [`references/scaffold-specification.schema.json`](references/scaffold-specification.schema.json);
`simplan check-scaffold` fails loud with fix-oriented messages.

Authoring judgment the schema/validator cannot express:
- `agents[].mode` — `active` for driver/master/driving agents; `passive` for monitor/slave/observer.
- `rm.inports` / `scoreboard.compare_txn` — name the agent txn(s) (`<module>_<agent>_txn`); the
  validator checks they resolve; you pick which agent is the RM input / the one observer.
- `testpoints[].covers[]` — cluster the `plan-data.json.check_hints[]` check_ids into testpoints
  (one-to-one / one-to-many / many-to-one; scenario testpoints you invent use `covers: []`).
- `skipped_checks[]` — any `check_hints[]` check_id covered by no testpoint MUST be listed here with
  a `reason` (e.g. `"static lint gate, no runtime testpoint"`), else the coverage gate fails.
- Every `power_scenarios[].sequence_ref` MUST appear in `sequences[].name` (see
  `references/power-scenarios-template.md`).

## Workflow

### Step 1: Read inputs, seed, determine scope

Read `design.md` + `manifest.json` (simulation-plan's declared inputs); if any required input is missing, close the run with the early-fail exit below (`fail_reason="external reference missing: <path>"`).

Run `simplan seed --workdir {workdir}` (whitelist no-clobber carry of the prior canonical plan + scaffold; **no-clobber**, so any freshly-authored workdir residue from an interrupted run is kept, and with no canonical it is a no-op — a first delivery. The judged `plan-review.json` is deliberately NOT carried — invalidate-on-rework).

Determine this round's edit scope from the first available source:
1. `{directive_path}`'s `fix_locus` when injected — Read that sibling file first; authoritative.
2. Else, on a `{failing_result}`, the attribution structure + this round's revision context read from the trigger file (field names come from the triggering stage's own `result.schema.json`), amended per the violation-type targeting table in Decision Rules. If the trigger is unreadable, close the run with the early-fail exit (`fail_reason="failing_result not readable: <path>"`).
3. Else compare the current specification content (`design.md` / `<child>.md`) against the seeded plan baseline to determine the affected sections.
4. Else (a first delivery, no prior canonical) full generation of plan + scaffold.

Amend only the in-scope sections. **Sections outside scope — together with their testpoint IDs / sequence names / `power_scenarios.sequence_ref` — are preserved verbatim** (stable anchors so coverage data / scaffold / SAIF caches do not drift on ID changes). When the seeded workdir already holds an updated version, that residue is the baseline. Any amendment to the plan voids any prior gate `clear`; Step 4 re-runs before the Step-5 user loop.

**Early-fail exit.** Whenever a documented failure cannot be resolved, first run `simplan seed --workdir {workdir}` (no-clobber; a no-op when no canonical exists — this covers a fail that fires before Step 1's seed ran, e.g. a missing external reference), then close the run with the finalize early-fail entry — never hand-assemble the envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --module {module} --status fail --fail-reason "<one-line reason>"
```

Reasons used by this skill: `external reference missing: <path>`; `failing_result not readable: <path>`; `specification minimum field completeness: <one-line missing-field summary>` (Step 2). finalize enumerates `artifacts[]` present-only, so the seeded carried product set all promotes — an early fail never shrinks canonical (the judged `plan-review.json` is the one exception: deliberately never carried on rework, per invalidate-on-rework).

### Step 2: Minimum field completeness self-check

Per `references/spec-input-contract.md`, validate the required columns of `design.md` §1.3 Feature Table / §1.4.1 Top-Level IO / §1.4.2 Inter-module Interconnects / §1.5 Interface Timing Scenarios; per-child `<child>.md §5 Verification Hints` (9-column required). On any miss, close the run with the Step-1 early-fail exit (`fail_reason="specification minimum field completeness: <one-line missing-field summary>"`).

### Step 3: Generate / update artifacts

Scope: a first delivery fully generates both artifacts; a narrowed scope (directive / `{failing_result}` / spec diff, per Step 1) amends only the targeted sections, preserving everything outside scope verbatim (Step 1's stable-anchor rule).

- Derive plan-data (run on every run that reaches this step):

  ```bash
  python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py derive-plan-data --workdir <spec-workdir> --output {workdir}/plan-data.json
  ```

  Writes `{workdir}/plan-data.json`; reads `manifest.json` + `design.md` + each `<child>.md §5`; cheap, deterministic, idempotent.
- Author the judgment fields into `scaffold-specification.json` (`agents` `{name, mode, interface_groups}`, `sequences`, `tests`, `rm`, `scoreboard`, `testpoints` `{id, bins, intent, covers}`, `skipped_checks`) and write `verification-plan.md` per the section outline. Author interface-group NAMES only (design.md §1.4.1); never hand-write signals, `primary_clock`/`reset`, or `inlined_check_hints[]`.
- **Materialize (deterministic):**

  ```bash
  python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py materialize-scaffold --plan-data {workdir}/plan-data.json --scaffold {workdir}/scaffold-specification.json
  ```

  Fills agent `interface.signals` (all group signals; clk/rst kept) + `transaction.fields` (clk/rst excluded via §1.4.1 Role), `primary_clock` (§1.6 Relationship=primary), `reset` (§1.4.1 Role=reset), and `inlined_check_hints[]` (from `covers[]`). On non-zero exit, read stderr for the exact cause (unknown/empty/duplicate `interface_group`, empty Role, no primary clock / reset, unknown `covers[]` check_id, non-numeric width), fix the scaffold or design.md §1.4.1/§1.6, and re-run.
- Power scenarios: load `references/power-scenarios-template.md`, materialize, write into both `verification-plan.md` §4 and `scaffold-specification.json.power_scenarios`.
- **Validate (gate):**

  ```bash
  python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py check-scaffold --scaffold {workdir}/scaffold-specification.json --plan-data {workdir}/plan-data.json
  ```

  Structural + semantic + coverage-matrix (every check_id covered-or-skipped; every `covers[]` resolves). Fix and re-run on non-zero exit. Runs on every run.
- **Cross-stage contract:** every `power_scenarios[].sequence_ref` MUST resolve to a `sequences[].name` — an unregistered ref has no backing SV class, so the downstream power-scenario emit fails closed. When a scenario needs independent stimulus, add the `sequences[]` entry (with `name` + `agent`) first. Full rules: the "sequence_ref naming rules and sequences[] sync" section in `references/power-scenarios-template.md` (loaded above).

### Step 4: Plan-adequacy review (self-dispatched Level-1 reviewer) — gating

Runs after `simplan check-scaffold` is green (Step 3) and before the Step-5 user review loop, on
every run that reaches it.
Dispatch ONE Level-1 reviewer per `references/plan-review-task-contract.md` (paths only — you
read no body): it judges testpoints vs spec (lens `coverage`) and check-strategy soundness
(lens `adequacy`).

> **Gate semantics (block-in-place).** A `gate=trip` here does **NOT** route out: it blocks
> `status=pass` **in place** and surfaces findings into the Step-5 user review-loop. finalize
> enforces this mechanically — a tripped-and-unwaived gate downgrades to a written
> `status=fail` (Step 6) — so the block cannot be talked past.

Dispatch, then reap on wake. Aggregate into `{workdir}/plan-review.json` (schema
`references/plan-review.schema.json`):
- `STATUS: DONE` + valid finding JSON → fold its findings in.
- `STATUS: BLOCKED` OR malformed JSON → record one `{tp_id:"plan", lens:"unavailable",
  severity:"minor", location:"-", summary:"review unavailable: <reason>"}` finding.
- `verdict="concerns"` iff any finding with `lens ≠ unavailable`; `has_critical` iff any
  `severity=critical`.

Run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py validate-review --review {workdir}/plan-review.json
```

On a non-zero exit, re-assemble the JSON yourself and re-run — do NOT re-dispatch the reviewer.
On exit 0 it prints
`{"gate":"trip"|"clear","flagged":[{tp_id,lens,severity}…],"must_ack":[{tp_id,severity}…]}`.
The Step-6 finalize owns both `stage_specific.plan_adequacy_gate` and `artifacts[]` — it
re-derives the verdict from the on-disk `plan-review.json` and lists the record itself; you
write neither by hand.

The verdict feeds Step 5 (block into the user loop; this stage never auto-fixes the plan).
- **`gate=trip`** → each `flagged` item is resolved or human-waived per the Step-5 waiver
  protocol; `status=pass` is governed by the Step-5 approve precondition.
- **`must_ack`** items are surfaced and acknowledged by approval, **deduped**: an adequacy item is
  re-surfaced only if NEW or CHANGED vs the prior promoted `plan-review.json` (match by
  `tp_id`+`summary`).
- **Review unavailable** → minimal `plan-review.json` with one `unavailable` finding (validator
  reports `gate=clear`); surface "review unavailable" as a **must-acknowledge** item at Step 5
  (deduped) — the user's approval explicitly acknowledges the gate did not run; do not silently
  pass. (Stops a SILENT disarm, not a CHRONIC one — the sim conformance backstop covers the
  TB-conformance subset meanwhile.)

### Step 5: User review loop

- Present `verification-plan.md` to the user, together with the `plan-review.json` verdict — `flagged` blocking items + `must_ack` advisory items (deduped to NEW/CHANGED per Step 4) + any `review unavailable` ack item (point to `plan-review.json` for summaries).
- **Waiver protocol (`gate=trip` is a hard block):** each `flagged` (coverage) item MUST be either resolved (user directs the revision; re-run Step 3 + Step 4) or **human-waived**: the operator supplies `{tp_id, lens, location, classification ∈ {false-positive, accepted-risk}, reason}`. **The `reason` is human-authored — you PROMPT the operator and block until provided, never auto-write it. No counter, no cross-round matching, no auto-downgrade.** For a **critical-severity coverage** waiver, surface: "no downstream stage re-checks testpoint-vs-spec (sim conformance judges TB-vs-testpoint) — terminal accept." Collect the waivers; they reach the envelope only via the Step-6 finalize `--waived`.
- Ask: approve / request changes / reject.
- approve → **Approve precondition (the single home — finalize re-checks it in-process at Step 6):** you MUST NOT accept `approve` unless `gate==clear` OR every `flagged` item is waived per the protocol above; re-run Step 4 first if not, then re-present.
- request changes → the revision voids any prior gate `clear` (invalidate-on-rework — a stale `clear` must not survive a plan edit); revise the artifacts incrementally per user feedback (return to Step 3), re-run Step 4, then come back and re-present.
- reject → close the run with the Step-6 finalize, passing `--status fail` (it writes `fail_reason="user rejected plan"`).

### Step 6: Build `{workdir}/result.json` (mandatory)

Run the host tool's finalize subcommand; do not hand-assemble the envelope or hand-count anything. Pass the human-gate state from Steps 1 and 5 — nothing else is needed:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --module {module} \
  [--waived '<json array of {tp_id,lens,location,classification,reason}>'] \
  [--status fail]            # user reject, or a documented early-fail exit \
  [--fail-reason "<one-line reason>"]   # early-fail exits only (Step 1) \
  [--revision '<one-line revision narrative>']   # a scoped revision only
```

finalize re-derives `status` from the Step-4 plan-adequacy gate (it re-runs `simplan validate-review`'s reduction over the on-disk `plan-review.json` and copies `{gate, flagged, must_ack}` into `stage_specific.plan_adequacy_gate`; `--waived` is merged in as `plan_adequacy_gate.waived[]` after a content check — a placeholder waiver with an empty `reason` or an unknown `classification` is rejected, exit 2), **enforces the Step-5 approve precondition itself** (a tripped-and-unwaived gate downgrades to a written `status=fail`), derives the summary counts as array-length reads of the promoted artifacts (`testpoint_count`/`power_scenario_count` + `scaffold_summary.{agent_count,sequence_count,test_count}` from `scaffold-specification.json`; `feature_count` = distinct `F-NN` in the `verification-plan.md` §3 Testpoints section), enumerates `artifacts[]` present-only (plan + scaffold + plan-review), and writes the complete `result.json`. `--status fail` wins unconditionally: with `--fail-reason` it is the early-fail exit (Step 1); without, it is the user reject (`fail_reason="user rejected plan"`). Exit 0 = result.json written (status pass or fail). A non-zero finalize exit is a program exception (BLOCKED), not a `status=fail`.

The plan's canonical revision history lives in `verification-plan.md` §5; `--revision` carries the one-line machine-readable copy. The plan's structured data (`agents` / `sequences` / `tests` / `testpoints` / `power_scenarios`) lives in `scaffold-specification.json` and is not duplicated into `stage_specific`.

## Decision Rules

- specification minimum field completeness not met → `status=fail` exit; do not force-generate the plan.
- User-requested minor tweaks vs. full overturn during review → minor tweaks take the in-loop revision path; full overturn takes the reject path.
- Equivalent power-scenario merging vs. splitting → same stimulus must be merged on `sequence_ref`; different `corner_intent` must be split into independent IDs.

**Violation-type targeting table** (when a `{failing_result}` carries multiple violation kinds, how to decide the primary edit target):

| Violation type | Primary edit target |
|---|---|
| Compile / smoke / regression class (behavioral or handshake errors) | `verification-plan.md` §2 (test strategy) + §5 (revision summary); `scaffold-specification.json.{rm, scoreboard}`. |
| Coverage-hole bin not in testpoints (`gaps_not_in_testpoints` non-empty — missing testpoint) | `verification-plan.md` §3 testpoints table + `scaffold-specification.json.testpoints[]` (**add** entries / extend `bins` to cover the missing holes). |
| Coverage-hole bin inside testpoints but `simulation-triage` returns `root_cause: rtl-design` (`gaps_in_testpoints` non-empty, stimulus_iterate exhausted — RTL dead code / plan over-spec) | `verification-plan.md` §3 testpoints table + `scaffold-specification.json.testpoints[]` (**narrow** `bins` to remove RTL-unreachable values; if the whole testpoint is unreachable, delete that testpoint and record the over-spec attribution in §5 revision summary). |
| Power-scenario failure | `verification-plan.md` §4 + `scaffold-specification.json.power_scenarios`. |

## Red Flags

| Excuse | Reality |
|---|---|
| "Most check_hints are covered — close enough to pass" | `simplan check-scaffold` enforces the matrix: every `check_hints[]` check_id must be in some `testpoints[].covers[]` or in `skipped_checks[]`. It is not a self-judgment you can rationalize past. |
| "This repair is automatic feedback — skip the review loop" | Every run runs the plan review loop; do not skip user approval because feedback came from a `{failing_result}`. |
| "I already know which power scenarios this module needs — I'll author them directly instead of loading the 9-scenarios template" | The standard set in `references/power-scenarios-template.md` is the required coverage basis — load it first, then materialize. `simplan check-scaffold` only checks `sequence_ref` resolution and the check-hints matrix; it does **not** verify a scenario came from the standard set, so an invented or dropped scenario passes the gate. No machine backstop — the template is the discipline. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Content drift between `verification-plan.md` and `scaffold-specification.json` | The two must correspond one-to-one; changing one requires syncing the other. |

## Completion Gate

- [ ] result.json was written by `simplan finalize` (it owns status / the derived counts / `plan_adequacy_gate` / `artifacts[]`; you supply only `--waived` / `--status` / `--fail-reason` / `--revision` from Steps 1 and 5).
- [ ] `simplan check-scaffold` passes — structural schema + semantic cross-refs + coverage-matrix (every `check_hints[]` check_id covered-or-skipped, each `covers[]` resolving); authoritative gate, runs on every run. This one gate fully validates the materialized scaffold contract (per-agent `interface_groups`/`interface.signals`, `primary_clock`/`reset`) — no separate checkbox per sub-layer.
- [ ] When `status=fail`, `stage_specific.fail_reason` records the missing item / user-rejection reason.
- [ ] `artifacts[]` has at least 2 entries (`verification-plan.md` + `scaffold-specification.json`); both files exist inside `{workdir}`.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] **The user has approved the review loop** (dialogue form — `status=pass` only after approval; `verification-plan.md` carries frontmatter `Status: approved`).
- [ ] `verification-plan.md` contains §1–§4 (a first delivery must include §1 / §2 / §3 / §4; a scoped revision adds §5 when a real diff is present).
- [ ] The number of entries in `verification-plan.md` §3 testpoints table matches the length of `scaffold-specification.json.testpoints[]`.
- [ ] The number of entries in `verification-plan.md` §4 power scenarios matches the length of `scaffold-specification.json.power_scenarios[]`.
- [ ] **Plan-adequacy gate (Step 4):** cleared per the Step-5 approve precondition (or the review was `unavailable` and acknowledged); `stage_specific.plan_adequacy_gate` and `plan-review.json` in `artifacts[]` are finalize-owned. `status=pass` requires that AND user approval.

## Return Contract

**Do not decide what happens after you complete** — control returns directly to the caller; the caller decides based on `result.json`.

### Re-entry and completion

Your sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`; a missing `result.json` is treated as incomplete (no cross-session "already complete" flag). `simplan seed` never clobbers workdir residue but never carries the gate review (`plan-review.json`) forward — invalidate-on-rework. Every re-entry re-runs the plan-adequacy gate (Step 4) on the current plan before finalize, so a compaction resumes without losing work and a stale `clear` cannot survive to finalize. Step 5 (the user review loop) **always re-runs**: it is idempotent with "ask the user again," re-presenting the current `verification-plan.md` for the user to reconfirm.

## Bundled References

- [`references/spec-input-contract.md`](references/spec-input-contract.md) — `design.md` (module-level) + per-child `<child>.md` (fan-out) minimum field completeness check + field-to-UVM derivation rules + complete derivation-chain example.
- [`references/power-scenarios-template.md`](references/power-scenarios-template.md) — power-scenarios template.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/plan-review.schema.json`](references/plan-review.schema.json) — gating plan-adequacy review schema (Step 4).
- [`references/plan-review-task-contract.md`](references/plan-review-task-contract.md) — self-dispatched reviewer sub-Task contract (Step 4).
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
