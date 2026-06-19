# `result.schema.json` Design Specification

> **Scope.** This document defines the design intent and field-inclusion rules for every
> `skills/<stage>/references/result.schema.json` in VeriPower. It is the canonical reference
> for what `result.json` is for, what belongs in it, and what does not.
>
> **Audience.** Anyone authoring a new stage schema, modifying an existing one, or reviewing
> a schema for compliance. Skills authors writing prose contracts in their SKILL.md should
> also read §3 (the principle) and §4 (the test questions).
>
> **Companion docs.** This document covers the **content** of `result.json` (what fields belong).
> For the **return contract** (when to write `result.json` vs. when to exit without writing),
> see `docs/skill-field-contract-design.md` (Return Contract field): envelope `status` enum
> is `{pass, fail}` only; "cannot start" is signaled by absence of `result.json`, "internal
> failure" by `status=fail` + `stage_specific.fail_reason`. The two documents are mutually
> reinforcing.

## 1. Background — what `result.json` is

Every stage produces exactly one `result.json` at `asic/<module>/<area>/<stage>/result.json`
(canonical) and `asic/<module>/<area>/<stage>/runs/<N>/result.json` (per-run). State.py
validates each `result.json` against `<skill>/references/result.schema.json`, which composes
the cross-stage `framework/references/schemas/envelope.schema.json` via JSON-Schema `$ref`.

`result.json` is **not** the stage's main artifact — design.md, scaffold-specification.json,
RTL filelists, netlists, and reports are the substantive outputs. `result.json` is the
metadata carrier that wraps them.

## 2. The three jobs `result.json` does

A clear schema design separates these:

| Role | What it carries | Who reads it |
|---|---|---|
| **R1 — Completion certificate** | "This stage finished, here is the verdict." Fields: `stage`, `status`, `produced_at`, `schema_version`, `module` | `state.py` for state-machine bookkeeping |
| **R2 — Artifact manifest** | "Here is where my outputs live." Fields: `artifacts[].path` (and optional per-item metadata) | `state.py.promote()` (hardlinking); downstream consumers (locating files) |
| **R3 — Structured handoff** | "Here is small machine-readable data downstream needs at envelope-read time." Fields: `stage_specific.*` | downstream code (Orchestrator, subagents) and downstream LLMs |

R1 and R2 are universal across all 9 stages and live in `envelope.schema.json`. R3 is
where per-stage schemas exist, and where most of the design tension lives.

## 3. The principle for `stage_specific`

> **`stage_specific` is for small, structured data that downstream consumers need at
> envelope-read time, that isn't naturally a separate artifact file.**

Two conditions, both required:

### 3.1 "Need at envelope-read time"

The downstream consumer is loading `result.json` and won't immediately load other artifact
files. Examples:

- The orchestrator (Orchestrator) loads spec's `result.json` to extract `ppa_targets` for prompt
  injection into synthesis/power-analysis dispatches; it does not open `design.md`.
- A rework-routing agent loads the failed stage's `result.json` to read `violations[]` for
  routing decisions; it does not open the stage's full reports.

If the downstream consumer is **already going to read** another artifact (design.md,
scaffold-specification.json, full reports) for its own work, data derivable from that
artifact does **not** belong in `stage_specific` — it would be duplication.

### 3.2 "Not naturally a separate artifact file"

Large structured data (full interface tables, full scenario lists, full coverage reports)
belongs in artifact files where it can be canonical, version-controlled per content, and
diffed naturally. Putting such data in `stage_specific` is a category error: the JSON form
is a diminished snapshot of what already exists better in a typed file.

`stage_specific` should be small (rough rule of thumb: a field's value is at most a
few hundred bytes when serialized). If it grows beyond that, it should be an artifact file
with a path in `artifacts[]`.

### 3.3 The failure-signaling field family

The family has four members: `fail_reason` (universal) and three structured classifiers, each
carried only by the stages whose routing needs it.

`fail_reason` — always `stage_specific.fail_reason` (the bare name in prose is shorthand) — is
the one-line free-text failure narrative, required on every `status=fail` in all nine stages. It
is read by human debuggers, by `simulation-triage`, and by `route.py` as `reason_hint` where the
router reads `result.json` directly.

The three structured classifiers follow one rule:

> A stage carries a structured failure-classification field iff its rework-routing target is a
> non-constant function of the failure type; the field's richness matches the routing function's.

They are three distinct axes, not renamings of one:

| Field | Axis | Stages |
|---|---|---|
| `failure_kind` | root-cause class | synthesis, timing-analysis, power-analysis |
| `failures[].category` | upstream attribution | power-analysis |
| `failure_phase` | pipeline position | simulation |

The per-stage `failure_kind` obligation and its `{infra, tooling, ppa}` enum semantics live in
`ARCHITECTURE.md §6.2`; this section classifies the family, it does not restate the obligation.
The remaining stages carry no classifier: `lint-cdc` and `simulation-plan` route to a fixed
target, and `specification` / `rtl-design` / `frontend-signoff` have no rework target — with a
constant or absent target there is nothing to classify, so `fail_reason` alone suffices.

The failure-**detail** payload (`violations[]`, `failures[]` beyond `.category`,
`failing_cases[]` / `coverage_gaps[]`) is a separate concern: consumed by the rework *target* to
scope its fix list, not by the router to choose one.

## 4. Test questions for adding or removing fields

When adding a new `stage_specific` field, all four answers must be "yes":

1. **Is there a real consumer** (today, not speculative) — code that reads the field, or
   an LLM agent at envelope-read time that benefits from at-a-glance access?
2. **Does the consumer NEED this at envelope-read time?** (Not "could use it if it were
   here" — but actually accesses `result.json` and stops, without loading other artifacts
   to reach the same answer.)
3. **Is the field small** (≤ a few hundred bytes serialized)? Larger = artifact file.
4. **Is the field NOT naturally derivable** from artifacts the consumer is already
   reading?

When reviewing an existing schema, ask the same four questions of every required field.
A "no" to any of them is grounds for deprecation.

## 5. Examples — what passes and what doesn't

### 5.1 Pass: spec `ppa_targets`
```json
"ppa_targets": [{"dim": "power_mw", "target": 50}, ...]
```
- Real consumer: `design-flow/SKILL.md:106-110` reads it, filters by `dim`, injects into
  synthesis/power-analysis prompts.
- Need at envelope-read time: yes, Orchestrator is dispatching and won't open design.md.
- Small: yes, typically 1–3 entries.
- Not derivable: yes, it's a structured PPA decision not directly in design.md tables.

### 5.2 Pass: sim-plan `fail_reason`
```json
"fail_reason": "design.md §1.4 missing direction column"
```
- Real consumer: rework-routing agents and human debuggers; the only place the failure
  narrative lives.
- Need at envelope-read time: yes, no other artifact carries this.
- Small: yes, single string.
- Not derivable: yes, not in any other artifact.

### 5.3 Fail: spec `interfaces` (correctly excluded — never added)
```json
"interfaces": [{"group": "APB", "signals": [{"name": "psel", "dir": "input", "width": 1}, ...]}]
```
- Real consumer: none. `derive_plan_data.py` parses `design.md` §1.4 directly via
  `load_interfaces(design_text)` — never reads `stage_specific.interfaces`.
- Need at envelope-read time: no, every consumer reads design.md anyway.
- Small: no, full interface tables can be hundreds of bytes per group.
- Not derivable: no, design.md §1.4 is the canonical source.

Three of four conditions fail.

### 5.4 Fail: sim-plan `testpoint_count` (vestigial — removed)
```json
"testpoint_count": 16
```
- Real consumer: none. Schema description claims *"counts allow consumers to size effort"*
  but no consumer ever materialized.
- Need at envelope-read time: no.
- Small: yes (one integer).
- Not derivable: no — `len(scaffold-specification.json.testpoints)`.

Two of four conditions fail; vestigial.

### 5.5 Boundary case: spec `top_module`
```json
"top_module": "alu16"
```
- Real consumer: prose convention only — `<TOP>.sdc` / `<TOP>.sgdc` filenames are anchored
  to this value; no programmatic reader.
- Need at envelope-read time: arguably yes for downstream LLM agents who want to know
  "what is this module called" without parsing design.md title.
- Small: yes (single string).
- Not derivable: arguably yes — design.md title is prose, not a structured field; rtl-design's
  result.json carries it but spec is upstream.

This is a judgment call. The convention-anchor role plus high LLM-orientation value justify
keeping it.

## 6. What does NOT belong in `result.json`

- **Orchestration-internal tracking metadata.** Fields like `__run` (run-identity check)
  belong in `task.json` / `events.jsonl`, owned by state.py. They are not cross-stage
  envelope concerns.
- **Documentation of what the stage produces.** That belongs in SKILL.md prose (the Input
  Artifacts / Output Artifacts sections). Schema = consumer contract, not stage description.
- **Aspirational fields ("may be useful someday").** If no consumer exists today, the field
  doesn't go in. Schema can be extended later when a real consumer appears (envelope's
  `additionalProperties: true` allows graceful extension).
- **Duplicates of artifact content** — covered by the §3.1 derivability rule.

## 7. Compliance checklist (for schema review)

When reviewing a `result.schema.json`, check:

- [ ] Every field in `stage_specific.required[]` answers "yes" to all four §4 test questions.
- [ ] Optional fields (in `properties` but not `required`) have a documented purpose
      (e.g., `fail_reason` only on `status=fail`).
- [ ] No field duplicates content already canonical in another artifact the consumer reads.
- [ ] Schema description accurately states the consumer relationship (not "may be useful"
      hand-waving).
- [ ] No orchestration-internal fields (run identity, dispatch state, etc.).
- [ ] `stage_specific.required[]` is minimum sufficient — every required field is load-bearing
      (adding one obliges the producer to emit it). (How `stage_specific` vs `schema_version` are
      versioned: see §8.)

## 8. Process for changing a schema

**What `schema_version` versions.** `schema_version` is the **completion-certificate (R1)
contract version** — the cross-stage `result.json` shape every stage shares. It is pinned
once, in `envelope.schema.json` (`const: 1`), and inherited by all nine stage schemas via their
`allOf` envelope `$ref`; no consumer branches on its value
(state.py validates it via the schema; nothing reads it to select behavior). A change confined
to ONE stage's `stage_specific` (R3) is versioned by that stage's own `result.schema.json` (its
`properties` + the `status` if/then gates), NOT by `schema_version` — bumping a shared marker for
a stage-local change would diverge it across stages for a reader that does not exist.

- **Adding / tightening a `stage_specific` field** (e.g. a new structured field required on
  `status=pass`): run the §4 test to justify it, add it to the stage's `properties` + the `status`
  if/then gate, and co-update the SKILL.md prose, test fixtures, and any consumer in the same
  change. **Do NOT bump `schema_version`** — the per-stage schema is the live R3 contract.
- **Removing / retyping a `stage_specific` field a consumer reads:** breaking for that consumer;
  verify consumers via grep and update the schema + every consumer + test fixtures together in one
  change (single-owner repo — there is no versioned external consumer to stage a migration for).
  This is coordinated co-update, not a `schema_version` bump.
- **Changing the shared envelope / completion-certificate contract** — a universal R1/R2 field in
  `envelope.schema.json`, the `status` enum, or the artifact-manifest shape (a change that alters
  what EVERY stage's `result.json` must look like): **bump `schema_version`** — a one-line
  change to the `const` in `envelope.schema.json`, inherited by every stage. This is the contract
  `schema_version` actually tracks.
- **Editing only a `description` string** (no change to shape, `required`, or types): not a
  contract change — do NOT bump `schema_version`.
