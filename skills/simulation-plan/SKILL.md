---
name: simulation-plan
description: Use when generating or evolving the verification plan, scaffold specification, testpoints, and power scenarios for a module; not for materializing UVM TB or running EDA tools.
---

# Verification Planning

Your sole responsibility: from `specification`, generate or evolve two artifacts — `verification-plan.md` (human-readable review anchor, with a testpoints section and a power-scenarios section) and `scaffold-specification.json` (machine-read contract, with `agents` / `sequences` / `tests` / `testpoints[]` / `power_scenarios[]`). **Do not read RTL source; do not invoke EDA tools.**

## When to Use

- First-time generation of plan + scaffold spec for a module.
- Incremental update triggered by a `specification` change.
- Plan / scaffold revisions from review feedback.

## Iron Rule

Your boundary:

- **Do not modify any file outside this run's workspace.** Only write artifacts under `{workdir}` and `result.json`.
- **Do not read RTL source, do not invoke EDA tools, and do not write `tb/uvm/` / `Makefile` / `vcd/`.** These belong to the TB-materialization stage.
- **Minimal edit on any re-dispatch with a prior valid `verification-plan.md` / `scaffold-specification.json` on disk.** Edit only what this round's task requires: `{directive_path}`'s `fix_locus`, when injected, is authoritative for scope; otherwise the violation-type targeting table (Decision Rules) or the incremental-update branch's spec-vs-baseline comparison sets the scope (already binding — see Step 1/Step 3: "unaffected parts... preserved verbatim"). Every section outside that scope MUST stay byte-identical to the prior run.
- **Freeze-reuse when nothing changed** — see the Step-1 branch list's freeze branch; never re-judge byte-identical content (it would regenerate `plan-review.json` and drop its `pin`).
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
| `{rework_trigger}` | Optional. The failed stage's canonical `result.json` path (field names per that stage's schema); absent → Step 1 selects freeze / session-resume / incremental-update / first-run. |
| `{directive_path}` | Optional. Fix-scope hint file; Read it first — priority over the trigger's attribution fields. |

### External reference inputs

| Path | Schema / Format | Use |
|---|---|---|
| `Design/specification/result.json` | `skills/specification/references/result.schema.json` | `specification` envelope — existence-checked at Step 1; its recorded digests feed the Step-1 `classify-delta` branch selection. You do not consume `ppa_targets`. |
| `Design/specification/design.md` | Custom markdown | Module-level design (§1.1–1.6: features / IO / interconnects / timing scenarios / clocks). Per-submodule content lives in each `<child>.md`. |
| `Design/specification/manifest.json` | Custom JSON (specification child registry) | `.module` fills the Top field in plan §1 Scope; child roster — drives per-child `§5` consumption by `simplan derive-plan-data`. |
| `Design/specification/<child>.md × N` | Custom markdown | Only `§5 Verification Hints` is consumed (via `simplan derive-plan-data`, tagging `check_hints[]` with `child`). |

When `{rework_trigger}` is injected, read additional context from the same directory as the trigger file (e.g., `failure_phase` / `failing_cases` / `coverage_gaps` / `gaps_not_in_testpoints` / `failures[]` / corresponding log and summary files). The specific read scope is driven by the trigger's content; do not enumerate it ahead of time.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `verification-plan.md` | Custom markdown (section outline below); after the review loop carries frontmatter `Status: approved` | Human-readable review anchor — drives the Step-5 user loop. |
| `scaffold-specification.json` | Custom JSON (field convention below); written after the Plan Gate | Machine-read contract (drives TB-materialization bootstrap + scaffold generation). |
| `plan-review.json` | `references/plan-review.schema.json` | Gating plan-adequacy review (Step 4 aggregate); promoted — the resume-guard re-reads the promoted copy. |
| `plan-data.json` | Custom JSON (derived by `simplan derive-plan-data`) | Intermediate cache, re-derived on every Step-3 pass (the freeze branch skips Step 3); **not** placed in `result.json.artifacts[]`. |

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

## 5. Revision Summary (append on trigger-driven revision / incremental update when a real diff is present)
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

### Step 1: Read inputs and select routing branch

Read `Design/specification/result.json` + `design.md` + `manifest.json`; if any required input is missing, close the run with the early-fail exit below (`fail_reason="external reference missing: <path>"`). When `{directive_path}` is injected, Read that sibling file first as a fix-scope hint (priority per the Input Artifacts variable description). Select among five branches in this order:

- **Freeze branch** (no trigger + no directive + `{workdir}` empty + `simplan classify-delta --canonical-result asic/{module}/Verification/simulation-plan/result.json --spec-dir asic/{module}/Design/specification` prints `verdict=freeze` — it verifies **both** the spec-input digest **and** the canonical products against the digests the prior pass recorded, so a hand-edited canonical classifies `proceed`, never freeze; a legacy baseline without a recorded `products_digest` likewise classifies `proceed`): run `simplan seed --workdir {workdir} --freeze` (whitelist byte-copy of the prior `verification-plan.md` / `scaffold-specification.json`, no-clobber; `--freeze` additionally carries `plan-review.json` — the byte-carry keeps its `pin` alive; `result.json` / `plan-data.json` are never seeded), then **skip Steps 2–5 outright** — the double digest match proves the products are the exact bytes the prior approval covered, so no reviewer re-dispatch and no user loop — and close with the Step-6 `simplan finalize`, passing `--waived` **verbatim** from the canonical `result.json` `stage_specific.plan_adequacy_gate.waived` when present (omit `--status` / `--revision` — nothing changed). A freeze run still ends with its own freshly-stamped `result.json`; a carried-in stale envelope is reaped `blocked` (`stale_result`), never as a verdict. On `first-run` / `proceed`, fall through to the branches below.
- **Trigger-driven rework** (`{rework_trigger}` injected): first run `simplan seed --workdir {workdir}` (whitelist no-clobber carry of the prior canonical plan + scaffold; the judged `plan-review.json` is deliberately NOT carried — invalidate-on-rework). Then read the attribution structure and the context for this round's revision from the trigger file (field names come from the triggering stage's own `result.schema.json`); use the seeded baseline (when `{workdir}` already holds an updated version, prefer the `{workdir}` copy) and amend per the violation-type targeting table in Decision Rules. If the trigger is unreadable, close the run with the early-fail exit (`fail_reason="rework_trigger not readable: <path>"`). A rework that amends the plan voids any prior gate `clear`; Step 4 re-runs before the Step-5 user loop.
- **Session-resume branch** (no trigger + `{workdir}/verification-plan.md` present + `{workdir}/result.json` absent): use the residual `{workdir}` artifacts as the baseline; depending on how complete the residue is, return to Step 3 or Step 5 to continue (preserve already-written sections verbatim; only fill in the missing parts). **Before continuing, if the plan-adequacy gate is not `clear`-or-all-`waived` (`plan-review.json` absent / `trip` / written before the latest plan edit), route to Step 4 first — not straight to Step 3 or Step 5.**
- **Incremental-update branch** (no trigger + `{workdir}` empty + canonical `Verification/simulation-plan/verification-plan.md` present): first run `simplan seed --workdir {workdir}` (same whitelist carry as the trigger branch). classify-delta has already proven the specification changed (`proceed`); compare the current specification content (`design.md` / `<child>.md`) against the seeded plan baseline to determine the affected sections, and amend only those. **Sections not affected — together with their testpoint IDs / sequence names / `power_scenarios.sequence_ref` — are preserved verbatim** (keep ID / naming as stable anchors so coverage data / scaffold / SAIF caches do not drift on ID changes). An incremental update that amends the plan likewise voids any prior gate `clear`; Step 4 re-runs before the Step-5 user loop.
- **First-run branch** (no trigger + `{workdir}` empty + canonical absent): full generation of plan + scaffold.

**Early-fail exit (all branches).** Whenever a documented failure cannot be resolved in-branch, close the run with the finalize early-fail entry — never hand-assemble the envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --module {module} --status fail --fail-reason "<one-line reason>"
```

Reasons used by this skill: `external reference missing: <path>`; `rework_trigger not readable: <path>`; `specification minimum field completeness: <one-line missing-field summary>` (Step 2). finalize enumerates `artifacts[]` present-only, so a seeded workdir's carried product set all promotes — an early fail never shrinks canonical (the judged `plan-review.json` is the one exception: deliberately not carried on non-freeze rework, per invalidate-on-rework).

### Step 2: Minimum field completeness self-check

Per `references/spec-input-contract.md`, validate the required columns of `design.md` §1.3 Feature Table / §1.4.1 Top-Level IO / §1.4.2 Inter-module Interconnects / §1.5 Interface Timing Scenarios; per-child `<child>.md §5 Verification Hints` (9-column required). On any miss, close the run with the Step-1 early-fail exit (`fail_reason="specification minimum field completeness: <one-line missing-field summary>"`).

### Step 3: Generate / update artifacts

Branch scope: **first-run** fully generates both artifacts; **trigger-driven rework** / **incremental-update** amend only the sections targeted by the violation-type targeting table in Decision Rules / specification diff, with unaffected parts — and their testpoint IDs / sequence names / `sequence_ref` — preserved verbatim as stable anchors; **session-resume** reuses the `{workdir}` residue and fills only the missing parts.

- Derive plan-data (run on every branch that reaches this step):

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

  Structural + semantic + coverage-matrix (every check_id covered-or-skipped; every `covers[]` resolves). Fix and re-run on non-zero exit. Runs on every branch.
- **Cross-stage contract:** every `power_scenarios[].sequence_ref` MUST appear in `sequences[].name` (`sequence_ref` is a reference into `sequences[]`, not an independent namespace — an unregistered ref has no backing sequence to materialize into an SV class, so the downstream power-scenario emit cannot resolve it and fails closed). When a power scenario needs independent stimulus (typical: clock-off / sustained idle / DVFS switching), first add a new entry to `sequences[]` (with `name` + `agent`), then have `power_scenarios[].sequence_ref` reference that `name`. See the final section "sequence_ref naming rules and sequences[] sync" in `references/power-scenarios-template.md`.

### Step 4: Plan-adequacy review (self-dispatched Level-1 reviewer) — gating

Runs after `simplan check-scaffold` is green (Step 3) and before the Step-5 user review loop, on
every branch that reaches it (the Step-1 freeze branch carries the prior review forward instead).
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
  [--revision '<one-line revision narrative>']   # trigger-driven rework only
```

finalize re-derives `status` from the Step-4 plan-adequacy gate (it re-runs `simplan validate-review`'s reduction over the on-disk `plan-review.json` and copies `{gate, flagged, must_ack}` into `stage_specific.plan_adequacy_gate`; `--waived` is merged in as `plan_adequacy_gate.waived[]` after a content check — a placeholder waiver with an empty `reason` or an unknown `classification` is rejected, exit 2), **enforces the Step-5 approve precondition itself** (a tripped-and-unwaived gate downgrades to a written `status=fail`), derives the summary counts as array-length reads of the promoted artifacts (`testpoint_count`/`power_scenario_count` + `scaffold_summary.{agent_count,sequence_count,test_count}` from `scaffold-specification.json`; `feature_count` = distinct `F-NN` in the `verification-plan.md` §3 Testpoints section), records the freeze digests (`input_digest` + `products_digest` — the next run's classify-delta compares both before permitting a freeze), enumerates `artifacts[]` present-only (plan + scaffold + plan-review), and writes the complete `result.json`. `--status fail` wins unconditionally: with `--fail-reason` it is the early-fail exit (Step 1); without, it is the user reject (`fail_reason="user rejected plan"`). Exit 0 = result.json written (status pass or fail). A non-zero finalize exit is a program exception (BLOCKED), not a `status=fail`.

The plan's canonical revision history lives in `verification-plan.md` §5; `--revision` carries the one-line machine-readable copy. The plan's structured data (`agents` / `sequences` / `tests` / `testpoints` / `power_scenarios`) lives in `scaffold-specification.json` and is not duplicated into `stage_specific`.

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
| "Most check_hints are covered — close enough to pass" | `simplan check-scaffold` enforces the matrix: every `check_hints[]` check_id must be in some `testpoints[].covers[]` or in `skipped_checks[]`. It is not a self-judgment you can rationalize past. |
| "This rework is trigger-driven, the feedback is automatic — skip the review loop" | All paths run the plan review loop; do not skip user approval because feedback came from a trigger. |
| "I already know which power scenarios this module needs — I'll author them directly instead of loading the 9-scenarios template" | The standard set in `references/power-scenarios-template.md` is the required coverage basis — load it first, then materialize. `simplan check-scaffold` only checks `sequence_ref` resolution and the check-hints matrix; it does **not** verify a scenario came from the standard set, so an invented or dropped scenario passes the gate. No machine backstop — the template is the discipline. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Content drift between `verification-plan.md` and `scaffold-specification.json` | The two must correspond one-to-one; changing one requires syncing the other. |

## Completion Gate

- [ ] result.json was written by `simplan finalize` (it owns status / the derived counts / `plan_adequacy_gate` / the freeze digests / `artifacts[]`; you supply only `--waived` / `--status` / `--fail-reason` / `--revision` from Steps 1 and 5).
- [ ] `simplan check-scaffold` passes — structural schema + semantic cross-refs; authoritative gate, runs on every branch.
- [ ] When `status=fail`, `stage_specific.fail_reason` records the missing item / user-rejection reason.
- [ ] `artifacts[]` has at least 2 entries (`verification-plan.md` + `scaffold-specification.json`); both files exist inside `{workdir}`.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] **The user has approved the review loop** (dialogue form — `status=pass` only after approval; `verification-plan.md` carries frontmatter `Status: approved`).
- [ ] `verification-plan.md` contains §1–§4 (first-run must include §1 / §2 / §3 / §4; trigger-driven revision / incremental update adds §5 when a real diff is present).
- [ ] Every `agents[]` entry declares a non-empty `interface_groups` array, and `simplan materialize-scaffold` ran successfully (each agent now carries a non-empty `interface.signals`). `simplan materialize-scaffold` + `simplan check-scaffold` fail loud here on an empty/underivable interface; sim-plan's own gate is authoritative — the scaffold contract is fully validated here.
- [ ] `scaffold-specification.json` contains the two single-object fields `primary_clock` (`dut_port_name` + `period_ns`) and `reset` (`dut_port_name`) (required; populated by `simplan materialize-scaffold` — a non-zero materialize exit in Step 3 is the fail path).
- [ ] The number of entries in `verification-plan.md` §3 testpoints table matches the length of `scaffold-specification.json.testpoints[]`.
- [ ] The number of entries in `verification-plan.md` §4 power scenarios matches the length of `scaffold-specification.json.power_scenarios[]`.
- [ ] `simplan check-scaffold` coverage-matrix layer passes: every `check_hints[]` check_id is in some `testpoints[].covers[]` or in `skipped_checks[]`, and every `covers[]` resolves.
- [ ] **Plan-adequacy gate (Step 4):** cleared per the Step-5 approve precondition (or the review was `unavailable` and acknowledged); `stage_specific.plan_adequacy_gate` and `plan-review.json` in `artifacts[]` are finalize-owned. `status=pass` requires that AND user approval.

## Return Contract

**Do not decide what happens after you complete** — control returns directly to the caller; the caller decides based on `result.json`.

### Session-resume semantics

Your sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`. A missing `result.json` is treated as incomplete; on re-entry, Workflow Step 1's five branches run again in order (trigger still injected → trigger-driven; otherwise `{workdir}` has residue → session-resume; otherwise freeze / incremental update / first-run by their conditions). Step 5 (the user review loop) **always re-runs**: it is idempotent with "ask the user again," re-presenting the current state of `verification-plan.md` for the user to reconfirm. There is no cross-session "already complete" flag.

> **Adequacy-gate resume-guard:** the Step-4 verdict lives in `{workdir}` scratch + the promoted canonical `plan-review.json`. The guard is enforced in Step 1's session-resume branch and at Step 5's approve precondition, so a compaction between review and finalize, or a stale `clear`, cannot yield an unreviewed/unre-reviewed pass.

## Bundled References

- [`references/spec-input-contract.md`](references/spec-input-contract.md) — `design.md` (module-level) + per-child `<child>.md` (fan-out) minimum field completeness check + field-to-UVM derivation rules + complete derivation-chain example.
- [`references/power-scenarios-template.md`](references/power-scenarios-template.md) — power-scenarios template.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/plan-review.schema.json`](references/plan-review.schema.json) — gating plan-adequacy review schema (Step 4).
- [`references/plan-review-task-contract.md`](references/plan-review-task-contract.md) — self-dispatched reviewer sub-Task contract (Step 4).
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
