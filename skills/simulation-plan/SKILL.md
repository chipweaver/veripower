---
name: simulation-plan
description: Use when generating or evolving the verification plan, scaffold specification, testpoints, and power scenarios for a module; not for materializing UVM TB or running EDA tools.
---

# Verification Planning

This skill's sole responsibility: from `specification`, generate or evolve two artifacts — `verification-plan.md` (human-readable review anchor, with a testpoints section and a power-scenarios section) and `scaffold-specification.json` (machine-read contract, with `agents` / `sequences` / `tests` / `testpoints[]` / `power_scenarios[]`). **Does not read RTL source; does not invoke EDA tools.**

## When to Use

- First-time generation of plan + scaffold spec for a module.
- Incremental update triggered by a `specification` change.
- Plan / scaffold revisions from review feedback.

## Iron Rule

Boundary of this skill:

- **Do not modify any file outside this run's workspace.** Only write artifacts under `{workdir}` and `result.json`.
- **Do not recursively dispatch subtasks** (do not call Task tool; sim-plan is Consumer-script class and must NOT use Task).
- **Do not read RTL source, do not invoke EDA tools, and do not write `tb/uvm/` / `Makefile` / `vcd/`.** These belong to the TB-materialization stage.
- **Do not decide what happens after this skill completes.** Return control to the caller.
- **Do not start before `specification/result.json` has `status=pass`.** Confirm precondition before entry.
- **Do not write `result.json.status=blocked`.** The envelope does not accept this value; any failure must be `status=fail` + `fail_reason`.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{rework_trigger}` | Optional. Caller-injected trigger-context file path (carries the attribution structure and the context needed for this round's revision; exact field names come from the triggering stage's own `result.schema.json`). When absent, Workflow Step 1 selects among session-resume / incremental-update / first-run branches. |
| `{orchestrator_context_path}` | Optional. Caller-injected fix-scope hint file path. When present, narrows the modification scope more precisely than the attribution fields inside `{rework_trigger}`. |

### External reference inputs

| Path | Schema / Format | Required | Use |
|---|---|---|---|
| `Design/specification/result.json` | `skills/specification/references/result.schema.json` | required (first-run) | `specification` envelope (`stage_specific.top_module` is used for the Top field in plan §1 Scope; structured data such as interfaces / clock domains / resets is read from `design.md` (module-level §1.1–1.6, §1.4.1 Top-Level IO, §1.6 Clocks and Frequencies) + per-child `<child>.md §5 Verification Hints` (via `derive_plan_data.py --workdir`). Not duplicated into `stage_specific`; `ppa_targets` is not consumed by this skill). |
| `Design/specification/design.md` | Custom markdown | required (first-run) | Module-level design (overview §1.1-1.6, §1.4.1 Top-Level IO table, §1.4.2 Inter-module Interconnects, §1.5 Interface Timing Scenarios, §1.6 Clocks and Frequencies). Per-submodule content lives in each `<child>.md` (see `Design/specification/<child>.md`). |
| `Design/specification/manifest.json` | Custom JSON (specification child registry) | required | Lists child names; drives per-child `<child>.md §5` consumption by `derive_plan_data.py`. |
| `Design/specification/<child>.md × N` | Custom markdown | required | Per-child design body; only `§5 Verification Hints` is consumed (by `derive_plan_data.py`), tagging `check_hints[]` with `child`. |

When `{rework_trigger}` is injected, read additional context from the same directory as the trigger file (e.g., `failure_phase` / `failing_cases` / `coverage_gaps` / `gaps_not_in_testpoints` / `power_sim_failures` / corresponding log and summary files). The specific read scope is driven by the trigger's content; do not enumerate it ahead of time.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `verification-plan.md` | Custom markdown (section outline below); after the review loop carries frontmatter `Status: approved` | Human-readable review anchor (overview + test strategy + testpoints table + power-scenarios materialization + revision summary). |
| `scaffold-specification.json` | Custom JSON (field convention below); written after the Plan Gate | Machine-read contract (drives TB-materialization bootstrap + scaffold generation). |
| `plan-data.json` | Custom JSON (derived by `derive_plan_data.py`) | Intermediate cache; **not** placed in `result.json.artifacts[]`. Derived by derive_plan_data.py on every branch (cheap, deterministic, idempotent). |

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

## 5. Revision Summary (append on trigger-driven revision / incremental update when a real diff is present)
Trigger context + revision highlights.

## Document Control
```

### `scaffold-specification.json` fields

LLM-authored (judgment): `module`, `top`, `agents[]` `{name, mode, interface_groups}`,
`sequences[]`, `tests[]`, `rm`, `scoreboard`, `testpoints[]` `{id, bins, intent, covers}`,
`power_scenarios[]`, and `skipped_checks[]` `{check_id, reason}`.

Script-injected by `materialize_scaffold.py` (do NOT hand-author): each agent's
`interface.signals` (all group signals) + `transaction.fields` (clk/rst excluded), `primary_clock`, `reset`, and each
`testpoints[].inlined_check_hints[]` (materialized from `covers[]` + plan-data,
`implementation_detail = verbatim-if-present-else-summary`).

Full structural shape: [`references/scaffold-specification.schema.json`](references/scaffold-specification.schema.json);
`validate_scaffold.py` fails loud with fix-oriented messages.

Authoring judgment the schema/validator cannot express:
- `agents[].mode` — `active` for driver/master/driving agents; `passive` for monitor/slave/observer.
- `rm.inports` / `scoreboard.compare_txn` — name the agent txn(s) (`<module>_<agent>_txn`); the
  validator checks they resolve, the LLM picks which agent is the RM input / the one observer.
- `testpoints[].covers[]` — cluster the `plan-data.json.check_hints[]` check_ids into testpoints
  (one-to-one / one-to-many / many-to-one; LLM-invented scenario testpoints use `covers: []`).
- `skipped_checks[]` — any `check_hints[]` check_id covered by no testpoint MUST be listed here with
  a `reason` (e.g. `"static lint gate, no runtime testpoint"`), else the coverage gate fails.
- Every `power_scenarios[].sequence_ref` MUST appear in `sequences[].name` (see
  `references/power-scenarios-template.md`).

## Workflow

### Step 1: Read inputs and select routing branch

Read `Design/specification/result.json` + `design.md` + `manifest.json`; if any required input missing, write `result.json` with `status=fail` + `stage_specific.fail_reason="external reference missing: <path>"`, then exit. Select among four branches in this order:

- **Trigger-driven rework** (`{rework_trigger}` injected): read the attribution structure and the context for this round's revision from the trigger file (field names come from the triggering stage's own `result.schema.json`); Read the canonical baseline (`Verification/simulation-plan/verification-plan.md` + `scaffold-specification.json`; when `{workdir}` already holds an updated version, prefer the `{workdir}` copy) as the revision baseline; amend per the violation-type targeting table in Decision Rules. If the trigger is unreadable → write `status=fail` + `fail_reason="rework_trigger not readable"`.
- **Session-resume branch** (no trigger + `{workdir}/verification-plan.md` present + `{workdir}/result.json` absent): use the residual `{workdir}` artifacts as the baseline; depending on how complete the residue is, return to Step 3 or Step 4 to continue (preserve already-written sections verbatim; only fill in the missing parts).
- **Incremental-update branch** (no trigger + `{workdir}` empty + canonical `Verification/simulation-plan/verification-plan.md` present): Read the canonical existing artifacts as the baseline; diff `Design/specification/result.json` against that baseline; amend only the affected sections incrementally. **Sections not affected by the diff — together with their testpoint IDs / sequence names / `power_scenarios.sequence_ref` — are preserved verbatim** (keep ID / naming as stable anchors so coverage data / scaffold / SAIF caches do not drift on ID changes).
- **First-run branch** (no trigger + `{workdir}` empty + canonical absent): full generation of plan + scaffold.

When `{orchestrator_context_path}` is injected, Read that sibling file first as a fix-scope hint (priority per the Input Artifacts variable description).

### Step 2: Minimum field completeness self-check

Per `references/spec-input-contract.md`, validate the required columns of `design.md` §1.3 Feature Table / §1.4.1 Top-Level IO / §1.4.2 Inter-module Interconnects / §1.5 Interface Timing Scenarios; per-child `<child>.md §5 Verification Hints` (9-column required). On any miss → write `result.json` (`status=fail`, `stage_specific.fail_reason` = one-line missing-field summary) and exit.

### Step 3: Generate / update artifacts

Branch scope: **first-run** fully generates both artifacts; **trigger-driven rework** / **incremental-update** amend only the sections targeted by the violation-type targeting table in Decision Rules / specification diff, with unaffected parts — and their testpoint IDs / sequence names / `sequence_ref` — preserved verbatim as stable anchors; **session-resume** reuses the `{workdir}` residue and fills only the missing parts.

- Derive plan-data (run on every branch): `python3 ${CLAUDE_PLUGIN_ROOT}/skills/simulation-plan/scripts/derive_plan_data.py --workdir <spec-workdir>` → `{workdir}/plan-data.json`. It reads `manifest.json` + `design.md` + each `<child>.md §5`; cheap, deterministic, idempotent.
- Author the judgment fields into `scaffold-specification.json` (`agents` `{name, mode, interface_groups}`, `sequences`, `tests`, `rm`, `scoreboard`, `testpoints` `{id, bins, intent, covers}`, `skipped_checks`) and write `verification-plan.md` per the section outline. Author interface-group NAMES only (design.md §1.4.1); never hand-write signals, `primary_clock`/`reset`, or `inlined_check_hints[]`.
- **Materialize (deterministic):** `python3 ${CLAUDE_PLUGIN_ROOT}/skills/simulation-plan/scripts/materialize_scaffold.py --plan-data {workdir}/plan-data.json --scaffold {workdir}/scaffold-specification.json`. Fills agent `interface.signals` (all group signals; clk/rst kept) + `transaction.fields` (clk/rst excluded via §1.4.1 Role), `primary_clock` (§1.6 Relationship=primary), `reset` (§1.4.1 Role=reset), and `inlined_check_hints[]` (from `covers[]`). On non-zero exit, read stderr for the exact cause (unknown/empty/duplicate `interface_group`, empty Role, no primary clock / reset, unknown `covers[]` check_id, non-numeric width), fix the scaffold or design.md §1.4.1/§1.6, and re-run.
- Power scenarios: load `references/power-scenarios-template.md`, materialize, write into both `verification-plan.md` §4 and `scaffold-specification.json.power_scenarios`.
- **Validate (gate):** `python3 ${CLAUDE_PLUGIN_ROOT}/skills/simulation-plan/scripts/validate_scaffold.py --scaffold {workdir}/scaffold-specification.json --plan-data {workdir}/plan-data.json`. Structural + semantic + coverage-matrix (every check_id covered-or-skipped; every `covers[]` resolves). Fix and re-run on non-zero exit. Runs on every branch.
- **Cross-stage contract:** every `power_scenarios[].sequence_ref` MUST appear in `sequences[].name` (the simulation stage materializes SV classes only from `sequences[]`; refs not registered there cause power-analysis emit to fail-closed). When a power scenario needs independent stimulus (typical: clock-off / sustained idle / DVFS switching), first add a new entry to `sequences[]` (with `name` + `agent`), then have `power_scenarios[].sequence_ref` reference that `name`. See the final section "sequence_ref naming rules and sequences[] sync" in `references/power-scenarios-template.md`.

### Step 4: User review loop

- Present `verification-plan.md` to the user.
- Ask: approve / request changes / reject.
- approve → proceed to Step 5.
- request changes → revise the artifacts incrementally per user feedback (return to Step 3), then come back to this step and re-present.
- reject → write `result.json` (`status=fail`, `stage_specific.fail_reason="user rejected plan"`) and exit.

### Step 5: Write `result.json`

(schema: `references/result.schema.json` + envelope).

- Required top-level fields: `schema_version: 1`, `stage: "simulation-plan"`, `module`, `produced_at` (ISO8601), `status`, `artifacts[]`, `stage_specific{}`.
- Under `stage_specific`, only `fail_reason` is hard-required by the schema when `status=fail` (one-line missing-field summary / user-rejection reason). Recommended informational fields (not schema-required): `testpoint_count` / `feature_count` / `scaffold_summary{agent_count, sequence_count, test_count}` / `power_scenario_count`, useful for status panels and analyzer prompt context.
- `status` ∈ {pass, fail} — never `blocked` (Iron Rule).

Note: the plan's structured data (`agents` / `sequences` / `tests` / `testpoints` / `power_scenarios`) lives in `scaffold-specification.json` and is not duplicated into `stage_specific`.

## Decision Rules

- specification minimum field completeness not met → `status=fail` exit; do not force-generate the plan.
- User-requested minor tweaks vs. full overturn during review → minor tweaks take the in-loop revision path; full overturn takes the reject path.
- Equivalent power-scenario merging vs. splitting → same stimulus must be merged on `sequence_ref`; different `corner_intent` must be split into independent IDs.

**Violation-type targeting table** (during trigger-driven rework, when multiple violation kinds appear together, how to decide the primary edit target):

| Violation type | Primary edit target |
|---|---|
| Compile / smoke / regression class (behavioral or handshake errors) | `verification-plan.md` §2 (test strategy) + §5 (revision summary); `scaffold-specification.json.{rm, scoreboard}`. |
| Coverage-hole bin not in testpoints (`gaps_not_in_testpoints` non-empty — missing testpoint) | `verification-plan.md` §3 testpoints table + `scaffold-specification.json.testpoints[]` (**add** entries / extend `bins` to cover the missing holes). |
| Coverage-hole bin inside testpoints but `simulation-triage` returns `root_cause: rtl-design` (`gaps_in_testpoints` non-empty, stimulus_iterate exhausted — RTL dead code / plan over-spec) | `verification-plan.md` §3 testpoints table + `scaffold-specification.json.testpoints[]` (**narrow** `bins` to remove RTL-unreachable values; if the whole testpoint is unreachable, delete that testpoint and record the over-spec attribution in §5 revision summary). |
| Power-scenario failure | `verification-plan.md` §4 + `scaffold-specification.json.power_scenarios`. |

## Red Flags

| Excuse | Reality |
|---|---|
| "Most check_hints are covered — close enough to pass" | `validate_scaffold.py --plan-data` enforces the matrix: every `check_hints[]` check_id must be in some `testpoints[].covers[]` or in `skipped_checks[]`. It is not a self-judgment you can rationalize past. |
| "This rework is trigger-driven, the feedback is automatic — skip the review loop" | All paths run the plan review loop; do not skip user approval because feedback came from a trigger. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Content drift between `verification-plan.md` and `scaffold-specification.json` | The two must correspond one-to-one; changing one requires syncing the other. |
| Skipping the 9-scenarios template and inventing power scenarios | Always load the template first, then materialize; missing scenarios are appended as S8 / S9. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written and passes schema validation (`schema_version: 1`).
- [ ] `validate_scaffold.py --plan-data` passes — structural schema + semantic cross-refs; authoritative gate, runs on every branch.
- [ ] When `status=fail`, `stage_specific.fail_reason` records the missing item / user-rejection reason.
- [ ] `artifacts[]` has at least 2 entries (`verification-plan.md` + `scaffold-specification.json`); both files exist inside `{workdir}`.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] **The user has approved the review loop** (dialogue form — `status=pass` only after approval; `verification-plan.md` carries frontmatter `Status: approved`).
- [ ] `verification-plan.md` contains §1–§4 (first-run must include §1 / §2 / §3 / §4; trigger-driven revision / incremental update adds §5 when a real diff is present).
- [ ] `scaffold-specification.json` contains the 5 array fields `agents` / `sequences` / `tests` / `testpoints` / `power_scenarios`. (schema/script enforced by validate_scaffold.py)
- [ ] Every `agents[]` entry declares a non-empty `interface_groups` array, and `materialize_scaffold.py` ran successfully (each agent now carries a non-empty `interface.signals`). `materialize_scaffold.py` + `validate_scaffold.py --plan-data` fail loud here on an empty/underivable interface; sim-plan's own gate is authoritative — the scaffold contract is fully validated here.
- [ ] `scaffold-specification.json` contains the two single-object fields `primary_clock` (`dut_port_name` + `period_ns`) and `reset` (`dut_port_name`) (required; populated by materialize_scaffold.py — a non-zero materialize exit in Step 3 is the fail path).
- [ ] The number of entries in `verification-plan.md` §3 testpoints table matches the length of `scaffold-specification.json.testpoints[]`.
- [ ] The number of entries in `verification-plan.md` §4 power scenarios matches the length of `scaffold-specification.json.power_scenarios[]`.
- [ ] `validate_scaffold.py --plan-data` coverage-matrix layer passes: every `check_hints[]` check_id is in some `testpoints[].covers[]` or in `skipped_checks[]`, and every `covers[]` resolves.
- [ ] **Every `power_scenarios[].sequence_ref` appears in `sequences[].name`** (refs not registered will not be materialized by the simulation stage → power-analysis emit will fail; see `references/power-scenarios-template.md`). (schema/script enforced by validate_scaffold.py)

## Return Contract

Control returns directly to the caller; the caller decides based on `result.json`.

### Session-resume semantics

This skill's sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`. A missing `result.json` is treated as incomplete; on re-entry, Workflow Step 1's four branches run again (trigger still injected → trigger-driven; otherwise `{workdir}` has residue → session-resume; otherwise canonical present → incremental update; otherwise → first-run). Step 4 (the user review loop) **always re-runs**: it is idempotent with "ask the user again," re-presenting the current state of `verification-plan.md` for the user to reconfirm. There is no cross-session "already complete" flag.

## Bundled References

- [`references/spec-input-contract.md`](references/spec-input-contract.md) — `design.md` (module-level) + per-child `<child>.md` (fan-out) minimum field completeness check + field-to-UVM derivation rules + complete derivation-chain example.
- [`references/power-scenarios-template.md`](references/power-scenarios-template.md) — power-scenarios template.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
