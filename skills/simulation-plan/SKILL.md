---
name: simulation-plan
description: Use when generating or evolving the verification plan, scaffold specification, testpoints, and power scenarios for a module; not for materializing UVM TB or running EDA tools.
---

# Verification Planning

Your sole responsibility: from `specification`, generate or evolve two artifacts — `verification-plan.md` (human-readable review anchor, with a testpoints section and a power-scenarios section) and `scaffold-specification.json` (machine-read contract, with `agents` / `sequences` / `tests` / `testpoints[]` / `power_scenarios[]`).

## Iron Rule

Your boundary:

- **Do not modify any file outside this run's workspace (`{workdir}`).**
- **Do not read RTL source, do not invoke EDA tools.**
- **Minimal edit on any re-dispatch with a prior valid `verification-plan.md` / `scaffold-specification.json` on disk.** Every section outside this round's scope (determined in Step 1) MUST stay byte-identical to the prior run.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{failing_result}` | Optional. The failed stage's canonical `result.json` path (field names per that stage's schema); when present, supplies this round's fix scope (Step 1). |
| `{directive_path}` | Optional. Fix-scope hint file; Read it first (it overrides the trigger's attribution fields). |

### External reference inputs

Each read-only upstream input's location is injected: read `inputs.json` in your `{workdir}`; below, `<key>` denotes that input's location, so you read `<key>/<subpath>` (`design`/`manifest`/`children` all resolve to the specification stage root).

| Path | Schema / Format | Use |
|---|---|---|
| `<design>/design.md` | Custom markdown | Module-level design (§1.1–1.5: features / IO / interconnects / timing scenarios). Per-submodule content lives in each `<child>.md`. |
| `<design>/clocks.json` | `specification/references/clocks.schema.json` | Clock definitions. `materialize-scaffold` reads it to derive `primary_clock`. |
| `<design>/features.json` | `specification/references/features.schema.json` | Feature list. You author testpoints and tests from it — read it directly, not via `plan-data.json`. |
| `<manifest>/manifest.json` | Custom JSON (specification child registry) | `.module` fills the Top field in plan §1 Scope; its `children[]` roster drives per-child `§5` consumption (via `simplan derive-plan-data`). |
| `<children>/<child>.md` × N | Custom markdown | Only `§5 Verification Hints` is consumed (via `simplan derive-plan-data`, tagging `check_hints[]` with `child`). |

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `verification-plan.md` | Custom markdown (section outline below); after the review loop carries frontmatter `Status: approved` | Human-readable review anchor for the Step-4 user loop. |
| `scaffold-specification.json` | Custom JSON (field convention below) | Machine-read contract; the downstream simulation stage's bootstrap consumes it to materialize the TB. |
| `plan-review.json` | `references/plan-review.schema.json` | Gating plan-adequacy review (Step 3); promoted to `artifacts[]`. |
| `plan-data.json` | Custom JSON (derived by `simplan derive-plan-data`) | Intermediate cache, re-derived on every Step-2 pass; **not** placed in `result.json.artifacts[]`. |

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
- `agents[].mode`: `active` for driver/master/driving agents; `passive` for monitor/slave/observer.
- `rm.inports` / `scoreboard.compare_txn`: name the agent txn(s) (`<module>_<agent>_txn`); the
  validator checks they resolve; you pick which agent is the RM input / the one observer.
- `testpoints[].covers[]`: cluster the `plan-data.json.check_hints[]` check_ids into testpoints
  (one-to-one / one-to-many / many-to-one; scenario testpoints you invent use `covers: []`).
- `skipped_checks[]`: any `check_hints[]` check_id covered by no testpoint MUST be listed here with
  a `reason` (e.g. `"static lint gate, no runtime testpoint"`), else the coverage gate fails.

## Workflow

### Fan-out Dispatch Contract

- **No Level 2 dispatch:** dispatch only Level-1 sub-Tasks; none dispatches a sub-Task of its own.
- **Dispatch-and-wait:** after dispatching, send a brief status and end the turn. Reap and aggregate each before proceeding, never against a partial set.

### Step 1: Read inputs, determine scope

Your previous round, if any, is already in `{workdir}`; edit it in place. Confirm `<design>/design.md` + `<manifest>/manifest.json` exist — do not read their bodies into the main thread; if a required input is missing, close the run with the early-fail exit below (`fail_reason="external reference missing: <path>"`).

Determine this round's edit scope from the first of these that applies:

- `{directive_path}` carries a `fix_locus`: Read that sibling file first; it is authoritative.
- a `{failing_result}` is injected: read the attribution structure and this round's revision context from the trigger file, amended per the Violation-type targeting table below; if the trigger is unreadable, close the run with the early-fail exit (`fail_reason="failing_result not readable: <path>"`).
- `{workdir}/changed-inputs.md` is present: it lists the input files that changed since this stage's last run; amend only the plan sections its `design.md` / `<child>.md` paths map to.
- a carried `{workdir}/verification-plan.md` has frontmatter `Status: approved` (a prior approved round, so a re-verify, not a first delivery): amend no section; re-run Step 3's gate on the carried plan and finalize; every section outside scope stays byte-identical.
- otherwise (a first delivery, or a prior round interrupted before approval): full generation of plan + scaffold.

**Early-fail exit.** Whenever a documented failure cannot be resolved, run finalize to close the run; never hand-assemble the envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --module {module} --status fail --fail-reason "<one-line reason>"
```

### Step 2: Generate / update artifacts

Produce `verification-plan.md` and `scaffold-specification.json` by running the pipeline below in order. When amending, keep testpoint IDs / sequence names / `power_scenarios.sequence_ref` stable: downstream coverage / scaffold / SAIF caches key off them, so renumbering one silently breaks the cache.

**Run `derive-plan-data`** to extract the raw spec fields (interfaces / scenarios / check-hints / wires) into `plan-data.json` (every run). Clocks and features are **not** among them — read `clocks.json` / `features.json` directly:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py derive-plan-data --workdir <design> --output {workdir}/plan-data.json
```

**Author the judgment fields** into `scaffold-specification.json`, and write `verification-plan.md` per the section outline. Which fields are yours vs script-injected: the `scaffold-specification.json` fields section above. How to map spec fields to UVM objects (agents from interface groups, sequences from scenarios, tests from features, RM / scoreboard from `§5` check-hints): `references/spec-input-contract.md`.

**Author power scenarios** per `references/power-scenarios-template.md` into `verification-plan.md` §4 and `scaffold-specification.json.power_scenarios`; every `sequence_ref` must resolve to a `sequences[].name` (add the `sequences[]` entry first when a scenario needs its own stimulus).

**Run `materialize-scaffold`** (every run) to fill the script-injected fields (see the fields section):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py materialize-scaffold --plan-data {workdir}/plan-data.json --scaffold {workdir}/scaffold-specification.json --clocks <design>/clocks.json
```

On a non-zero exit, read stderr for the cause, fix the scaffold or (for a clock defect) re-run specification — `clocks.json` is its output, not yours — and re-run.

**Run `check-scaffold`** (the gate; every pass) to validate the scaffold's structure, semantics, and coverage-matrix (every check_id covered-or-skipped; every `covers[]` resolves):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py check-scaffold --scaffold {workdir}/scaffold-specification.json --plan-data {workdir}/plan-data.json
```

Fix and re-run on a non-zero exit.

### Step 3: Plan-adequacy review (gating)

On every run, dispatch ONE reviewer per `references/plan-review-task-contract.md`, paths only: you read no body. The two lenses, the gating split, and scope live in that contract; do not restate them here.

> **Gate semantics (block-in-place).** A `gate=trip` is not an automatic fail-out: it does **NOT** itself route rework or write `status=fail`. It blocks `status=pass` **in place** and surfaces the findings to the Step-4 user review loop, where a human resolves each one (revise, waive, or reject).

Aggregate the reaped report into `{workdir}/plan-review.json` (schema `references/plan-review.schema.json`):
- On `STATUS: DONE` + valid JSON, fold the findings in.
- On `STATUS: BLOCKED` or unparseable JSON, record one `unavailable`-lens finding (`tp_id: plan`, `severity: minor`), so a crashed reviewer can't read as a silent clean pass.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py validate-review --review {workdir}/plan-review.json
```

On a non-zero exit, the JSON you assembled is invalid: stderr names the schema violation. Re-assemble and re-run (a main-thread fix, NOT a re-dispatch).

On exit 0 it prints the gate verdict `{"gate":"trip"|"clear","flagged":[{tp_id,lens,severity}…],"must_ack":[{tp_id,severity}…]}`: the mechanical `lens × severity` reduction, computed by the script, not by eye. You copy nothing into the envelope; finalize re-derives it from the promoted `plan-review.json`.

On `clear`, proceed to the Step-4 user loop; on `trip`, the findings are resolved there (block-in-place, above). `must_ack` advisories and any `unavailable` markers ride to that loop for acknowledgement. This stage never auto-fixes the plan.

### Step 4: User review loop (human)

Path-handoff — present these to the user, echoing no body: the `verification-plan.md` path and the `plan-review.json` verdict summaries:
- `flagged` (coverage) blocking items;
- `must_ack` (adequacy) advisory items;
- any `review unavailable` acknowledgement item.

Surface a `must_ack` or `review unavailable` item only if NEW or CHANGED vs the prior promoted `plan-review.json` (match by `tp_id`+`summary`); an unchanged one was already acknowledged (anti rubber-stamp). A `review unavailable` item means the gate did not run, so the approval explicitly acknowledges it, never a silent clean pass.

**Waiver protocol (the single home).** When `gate==trip`, each `flagged` (coverage) item must be either fixed (via a request for changes, below) or **human-waived**: the operator supplies `{tp_id, lens, location, classification ∈ {false-positive, accepted-risk}, reason}`, whose `reason` is human-authored (you PROMPT the operator and block until provided, never auto-write it; no counter, no cross-round matching, no auto-downgrade). For a **critical-severity coverage** waiver, surface: "no downstream stage re-checks testpoint-vs-spec (sim conformance judges TB-vs-testpoint), so this is a terminal accept." Waivers reach the envelope only via the Step-5 finalize `--waived`.

Then the user approves, requests changes, or rejects:
- **approve**: accept only if `gate==clear` OR every `flagged` item is waived per the protocol above (the **approve precondition**, which finalize re-checks in-process); resolve first if not, then re-present.
- **request changes**: revise the artifacts incrementally (return to Step 2), re-run Step 3, then re-present; the revision voids any prior gate `clear` (invalidate-on-rework, so a stale `clear` cannot survive a plan edit).
- **reject**: close the run with the Step-5 finalize, passing `--status fail` (it writes `fail_reason="user rejected plan"`).

### Step 5: Build `{workdir}/result.json` (script, mandatory)

Run finalize to write the stage's `result.json`; never hand-assemble the envelope or hand-count anything:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --module {module} \
  [--waived '<json array of {tp_id,lens,location,classification,reason}>'] \
  [--status fail]            # user reject, or a documented early-fail exit \
  [--fail-reason "<one-line reason>"]   # early-fail exits only (Step 1) \
  [--revision '<one-line revision narrative>']   # a scoped revision only
```

You supply only the human-gate outcome from Steps 1 and 4: `--waived` (`[]` if none), and on a fail `--status fail` (with `--fail-reason` for a Step-1 early-fail; without, the user reject). finalize enforces the Step-4 approve precondition itself, **downgrading a computed pass to a written `status=fail`** when the gate is tripped and not fully waived; a malformed `--waived` (empty `reason` or unknown `classification`) is rejected as BLOCKED (exit 2). Exit 0 = `result.json` written (status pass or fail); a non-zero exit is a program exception (BLOCKED, reason on stderr), not a `status=fail`.

## Violation-type targeting (repair scope)

When a `{failing_result}` carries multiple violation kinds, decide the primary edit target by kind:

| Violation type | Primary edit target |
|---|---|
| Compile / smoke / regression class (behavioral or handshake errors) | `verification-plan.md` §2 (test strategy) + §5 (revision summary); `scaffold-specification.json.{rm, scoreboard}`. |
| Coverage-hole bin not in testpoints (`gaps_not_in_testpoints` non-empty — missing testpoint) | `verification-plan.md` §3 testpoints table + `scaffold-specification.json.testpoints[]` (**add** entries / extend `bins` to cover the missing holes). |
| Coverage-hole bin inside testpoints (`gaps_in_testpoints` non-empty), `simulation-triage` returns `root_cause: simulation-plan` (plan over-spec: a bin the RTL cannot legally reach) | `verification-plan.md` §3 testpoints table + `scaffold-specification.json.testpoints[]` (**narrow** `bins` to remove the unreachable values; if the whole testpoint is unreachable, delete it and record the over-spec attribution in §5 revision summary). |
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

- **Mechanical gate:** `simplan check-scaffold` passes (structural schema + semantic cross-refs + coverage-matrix: every `check_hints[]` check_id covered-or-skipped, each `covers[]` resolving), run on every run.
- **Semantic gate:** the Step-3 plan-adequacy gate cleared per the Step-4 approve precondition (or the review was `unavailable` and acknowledged); `stage_specific.plan_adequacy_gate` written; `plan-review.json` in `artifacts[]`.
- **Human gate:** the user approved the review loop; `verification-plan.md` carries frontmatter `Status: approved` (`status=pass` only after approval).
- **Finalize:** `simplan finalize` wrote `result.json` (Step 5), owning status / `plan_adequacy_gate` / `fail_reason` (on fail) / `artifacts[]`; its verdict is schema-validated externally, not by you.
- **Plan consistency:** `verification-plan.md` has §1–§4 (a scoped revision adds §5 on a real diff), and its §3 testpoints / §4 power-scenarios counts match `scaffold-specification.json.testpoints[]` / `.power_scenarios[]`.
- No Iron Rule or Red Flag was triggered.

## Return Contract

**Do not decide what happens after you complete**; control returns to the caller, which decides from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is incomplete (no cross-session "already complete" flag), so a repair round or a compaction resume just re-enters and re-runs the pipeline idempotently.

## Bundled References

- [`references/spec-input-contract.md`](references/spec-input-contract.md) — how the `plan-data.json` fields (extracted from `design.md` + per-child `<child>.md §5`) map to the scaffold objects this stage authors, with a worked APB example.
- [`references/power-scenarios-template.md`](references/power-scenarios-template.md) — the standard 9-power-scenarios table + per-module materialization guide.
- [`references/scaffold-specification.schema.json`](references/scaffold-specification.schema.json) — structural schema for `scaffold-specification.json` (the machine contract); enforced by `simplan check-scaffold`.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/plan-review.schema.json`](references/plan-review.schema.json) — gating plan-adequacy review schema (Step 3).
- [`references/plan-review-task-contract.md`](references/plan-review-task-contract.md) — self-dispatched reviewer sub-Task contract (Step 3).
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
