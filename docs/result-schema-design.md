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

`result.json` is **not** the stage's main artifact — design.md, the plan sidecars,
RTL filelists, netlists, and reports are the substantive outputs. `result.json` is the
metadata carrier that wraps them.

## 2. The three jobs `result.json` does

| Role | What it carries | Who reads it |
|---|---|---|
| **R1 — Completion certificate** | "This stage finished, here is the verdict." Fields: `stage`, `status`, `produced_at`, `module` | `kernel.py` for outcome/status bookkeeping |
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
narrative, required on every `status=fail` in all nine stages. It is read by human debuggers, by
`simulation-triage`, and by the fix owner as the account behind the naming that woke it.

**Classification and attribution are different questions, and only one of them is a field.**
`fix_owner` answers *who must act*: a rule name the stage writes from what it read in the raw
tool output, checked against the derived input closure and nothing else (`ARCHITECTURE.md §5.4`).
It is deliberately not an enum. A classifier answers *what kind of failure this was*, for the
human and the fix owner reading the envelope; it selects no target:

| Field | Axis | Stages |
|---|---|---|
| `failure_kind` | the tool-level failure class no violation list can express | synthesis, timing-analysis, power-analysis |
| `failures[].category` | a condition the parser detected itself | power-analysis |
| `failure_phase` | pipeline position | simulation |

A classifier earns its place only where the answer is decidable by the deriving code **and is
not already in the envelope**. `lint-cdc` carries none on either count: its `violations[]` rows
already give rule, `file:line` and reason, so any summary over them restates the same data one key
away; and the one thing not in them — whose artifact must change — a rule prefix cannot decide,
because a missing-declaration violation is reported at the RTL line that used the undeclared
object while the fix belongs in the SGDC. `power-analysis` keeps `category` narrowed to the three
conditions its parser detects on its own (`saif_dump`, `ptpx_data`, `tooling`); the five values
that named an upstream instead were a proxy for `fix_owner`, decoded by a table, and are retired.
`specification` carries no classifier and no `fix_owner`: its input closure is empty, so it could
only ever name itself.

The failure-**detail** payload (`violations[]`, `failures[]`, `failing_cases[]` /
`coverage_gaps[]`) is a separate concern again: consumed by the fix owner to scope its fix list.

**Note:** §§4–7 (test-question checklist, worked examples, the "what does not belong" list, compliance checklist) are intentionally absent — folded into §3 or now enforced by the schema and its tests. Section numbers are preserved to match the design-doc template positions.

## 8. Process for changing a schema

**`result.json` carries no version stamp.** It used to: `schema_version` was pinned
`{"const": 1}` in the envelope and required of every stage, and the process here described when
to bump it. Nothing ever branched on the value — this document said so in the same breath as
prescribing the bump — and the project replaces wholesale rather than shipping compatibility
shims, so the bump the protocol described was never going to happen. A `result.json` is
regenerated every run; the schema on disk is the contract, and a stale envelope fails it
directly rather than being recognised by a marker.

The four review records (`spec-review` / `semantic-review` / `conformance-review` /
`plan-review`) DO keep `schema_version`, and for the reason the envelope did not: they are
LLM judgments, not re-derivable, and an old one on disk cannot be regenerated to match a new
shape. A durable record that outlives its schema needs to say which schema it was written to.

When adding or removing a `stage_specific` field, co-update the stage's `result.schema.json`,
SKILL.md prose, test fixtures, and any consumer in the same change (single-owner repo — no
versioned external consumer to stage a migration for).
