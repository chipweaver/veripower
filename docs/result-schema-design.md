# `result.schema.json` Design Specification

> **Scope.** This document defines the design intent and field-inclusion rules for every
> `skills/<stage>/references/result.schema.json` in VeriPower. It is the canonical reference
> for what `result.json` is for, what belongs in it, and what does not.
>
> **Audience.** Anyone authoring a new stage schema, modifying an existing one, or reviewing
> a schema for compliance.
>
> **Companion doc.** This document covers the **content** of `result.json` (what fields belong).
> For the **return contract** (when to write `result.json` vs. when to exit without writing),
> see `docs/skill-field-contract-design.md`.

## 1. Background — what `result.json` is

Every stage produces exactly one `result.json` at `asic/<module>/<area>/<stage>/result.json`
(canonical) and `asic/<module>/<area>/<stage>/runs/<N>/result.json` (per-run). `kernel.py`
validates each `result.json` against `<skill>/references/result.schema.json`, which composes
the cross-stage `framework/references/schemas/envelope.schema.json` via JSON-Schema `$ref`.

`result.json` is **not** the stage's main artifact — design.md, scaffold-specification.json,
RTL filelists, netlists, and reports are the substantive outputs. `result.json` is the
metadata carrier that wraps them.

## 2. The three jobs `result.json` does

| Role | What it carries | Who reads it |
|---|---|---|
| **R1 — Completion certificate** | "This stage finished, here is the verdict." Fields: `stage`, `status`, `produced_at`, `schema_version`, `module` | `kernel.py` for outcome/status bookkeeping |
| **R2 — Artifact manifest** | "Here is where my outputs live." Fields: `artifacts[].path` (and optional per-item metadata) | `kernel.py`'s reap-time `promote()` (hardlinking); downstream consumers locating files |
| **R3 — Structured handoff** | "Here is small machine-readable data downstream needs at envelope-read time." Fields: `stage_specific.*` | downstream code (Orchestrator, subagents) and downstream LLMs |

R1 and R2 are universal across all stages and live in `envelope.schema.json`. R3 is
where per-stage schemas exist, and where most of the design tension lives.

## 3. The principle for `stage_specific`

> **`stage_specific` is for small, structured data that downstream consumers need at
> envelope-read time, that isn't naturally a separate artifact file.**

Two conditions, both required. Failure on either means the field does not belong in
`stage_specific`.

### 3.1 "Need at envelope-read time"

The downstream consumer loads `result.json` and won't immediately load other artifact
files. The Orchestrator reads spec's `result.json` to extract `ppa_targets` without
opening `design.md`; a rework-routing agent routes on `violations[]` without opening
full reports.

If the downstream consumer is already going to read another artifact for its own work,
data derivable from that artifact does **not** belong in `stage_specific` — it would be
duplication.

### 3.2 "Not naturally a separate artifact file"

Large structured data (full interface tables, full scenario lists, full coverage reports)
belongs in artifact files where it can be canonical, version-controlled per content, and
diffed naturally. Putting such data in `stage_specific` is a category error: the JSON form
is a diminished snapshot of what already exists better in a typed file. A field's
serialized value should be at most a few hundred bytes; larger means it should be an
artifact file with a path in `artifacts[]`.

**What does not belong in `result.json`:**

- **Orchestration-internal tracking metadata.** Fields like `__run` belong in
  `events.jsonl`, owned by `kernel.py`. They are not cross-stage envelope concerns.
- **Documentation of what the stage produces.** That belongs in SKILL.md prose (the Input
  Artifacts / Output Artifacts sections). Schema = consumer contract, not stage description.
- **Aspirational fields ("may be useful someday").** If no consumer exists today, the field
  doesn't go in. `envelope.schema.json`'s `additionalProperties: true` allows graceful
  extension later when a real consumer appears.
- **Duplicates of artifact content** — covered by the §3.1 derivability rule.

### 3.3 The failure-signaling field family

The family has four members: `fail_reason` (universal) and three structured classifiers.

`fail_reason` — always `stage_specific.fail_reason` — is the one-line free-text failure
narrative, required on every `status=fail` in all nine stages. It is read by human debuggers,
by `simulation-triage`, and by `route.py` as `reason_hint`.

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
`failing_cases[]` / `coverage_gaps[]`) is a separate concern: consumed by the rework target to
scope its fix list, not by the router to choose one.

**Note:** §§4–7 (test-question checklist, worked examples, the "what does not belong" list, compliance checklist) are intentionally absent — folded into §3 or now enforced by the schema and its tests. Section numbers are preserved to match the design-doc template positions.

## 8. Process for changing a schema

**`schema_version` tracks the cross-stage envelope contract, not per-stage `stage_specific`.**
`schema_version` is the completion-certificate (R1) contract version — the cross-stage
`result.json` shape every stage shares. It is pinned once in `envelope.schema.json`
(`const: 1`) and inherited by all stage schemas via `allOf`; no consumer branches on its value.

A change confined to one stage's `stage_specific` (R3) is versioned by that stage's own
`result.schema.json` — NOT by `schema_version`. Bumping a shared marker for a stage-local
change would diverge it across stages for a reader that does not exist.

Only a change to the shared envelope itself — a universal R1/R2 field in `envelope.schema.json`,
the `status` enum, or the artifact-manifest shape — warrants a `schema_version` bump, because
that changes what every stage's `result.json` must look like. A change to a `description`
string (no shape, `required`, or type change) is not a contract change and never bumps
`schema_version`.

When adding or removing a `stage_specific` field, co-update the stage's `result.schema.json`,
SKILL.md prose, test fixtures, and any consumer in the same change (single-owner repo — no
versioned external consumer to stage a migration for).
