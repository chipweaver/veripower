# `framework/` — VeriPower Plugin Framework Layer

This directory is the **framework layer** of the VeriPower plugin: the protocol,
schemas, and CLI tooling that the stage skills and orchestrator both work against.
It sits one layer above `skills/` — every skill produces or consumes artifacts
defined here, but no skill *owns* this layer.

> **Why "framework" and not "shared"?** "Shared" implied "multi-consumer" — but
> three of the four items below have `design-flow` as their primary caller, and
> they belong here for a different reason: they're the **infrastructure** that
> defines what every skill (and the orchestrator) plugs into.

## Contents

### `references/schemas/envelope.schema.json` — cross-stage producer contract

Every stage's `result.json` validates against its own `references/result.schema.json`,
which composes this envelope via JSON Schema `$ref`. Every conforming result.json
carries the universal fields (`stage`, `status`, `module`, `produced_at`,
`schema_version`, `artifacts[]`) that any reader can rely on regardless of which
stage produced the file. **Genuinely cross-stage** — every producer references it; every
consumer (orchestrator, tests, debugging tools) validates against it.

### `references/schemas/events/` — audit-log schema

Schemas for `asic/<module>/events.jsonl` entries (one schema file per event
type: `dispatch`, `outcome`, `rework_decision`, `cascade`, `escalation`,
`invalidate`, `debug_dispatch`). Events are written by `state.py` (via Orchestrator)
and **readable by anyone debugging or auditing a pipeline run** — not just the
writer.

### `references/prompts/stage-subagent.md.tpl` — dispatcher prompt template

The prompt template the orchestrator renders when dispatching a stage subagent.
Defines the canonical injection points (`{workdir}`, `{module}`,
`{rework_trigger}`, `{orchestrator_context_path}`) that every stage skill
documents in its SKILL.md input table.

### `scripts/state.py` — orchestration-protocol CLI

A standalone Python CLI implementing the state machine. 8 commands:
`init`, `status`, `dispatch`, `reap`, `rework`, `invalidate-stage`, `convergence`, `log`.
The authoritative source for stage state; re-exports `PREREQ_OF` and other DAG constants from `topology.py`.

### `scripts/topology.py` — pipeline DAG structural SSoT

The authoritative source for `PREREQ_OF` (the stage DAG), `FORWARD_PRIORITY`, `SKILL_OF`, `eligible()`, and `descendants()`. Dependency-light leaf with no I/O — importable without pulling in `jsonschema`.

### `scripts/orchestrate.py` — the decider

A standalone Python CLI that reads on-disk state and returns exactly one action per call (`orchestrate.py decide --module <M> [--wake <stage>:<run>] [--analysis -]`). The `design-flow` Orchestrator executes this action and loops until `YIELD`/`DONE`/`ESCALATE`. All deterministic control-loop logic lives here (composes `route.py`, `eligible()`, and `convergence()`); the Orchestrator is a thin executor.

Primary caller is the `design-flow` Orchestrator loop, but the tool is **runnable
by anyone**: humans manually driving a pipeline, tests, CI, future automated
runners. Not a private library imported by one skill — a project CLI that
implements the protocol the framework defines.

### `scripts/route.py` — deterministic rework-target router

The sole home of the failure→target maps: a pure, stateless evaluator that maps a
stage failure to a rework target (or to `ESCALATE` / `NEED_INPUT`). Composed
unchanged inside `orchestrate.py` — an import-only internal, never invoked directly.

### `scripts/artifacts.py` — artifact-lifecycle internals

The promote + trace-mirroring helpers imported by `state.py` (canonical-view
rebuild, hardlink promote, async-transcript mirroring). An import-only internal —
`state.py` is its only caller; never invoked directly.

## Ownership model

| Item | Producer | Primary consumer | Available to |
|---|---|---|---|
| `envelope.schema.json` | Stage skills (via $ref) | Anyone reading `result.json` | All skills + orchestrator + tests |
| `events/*.schema.json` | `state.py` | `state.py` + auditors | All consumers of `events.jsonl` |
| `stage-subagent.md.tpl` | n/a (template) | `design-flow` (renderer) | Designers studying the protocol |
| `state.py` | n/a (binary) | `design-flow` | tests / manual operators |
| `topology.py` | n/a (constants) | `state.py` + `orchestrate.py` (import) | tests / anyone importing the DAG |
| `orchestrate.py` | n/a (binary) | `design-flow` (decider) | tests / manual operators / CI |
| `route.py` | n/a (pure fn) | `orchestrate.py` (import) | internal / tests |
| `artifacts.py` | n/a (internal) | `state.py` (import) | internal only |

## What does NOT belong here

- Per-stage logic, schemas, or templates — those live in `skills/<stage>/`.
- Skill-private constants — those live in `skills/<stage>/references/`.
- Project-wide documentation — that lives in `docs/`.
- Plugin metadata (CLAUDE.md, ARCHITECTURE.md, README.md) — top-level.

## Relationship to `skills/`

`skills/` contains *components* (stage skills + orchestrator); `framework/`
contains the *protocol* those components implement. A new stage skill would:

1. Author `skills/<new-stage>/references/result.schema.json` that `$ref`s
   `framework/references/schemas/envelope.schema.json`.
2. Optionally add a new event type schema under `framework/references/schemas/events/`
   (only if introducing a new event class — usually existing types suffice).
3. Add itself to `PREREQ_OF` in `framework/scripts/topology.py` (re-exported from `state.py`).

No changes to `framework/` should ever be made in service of a single skill's
private needs — those go under that skill's own directory.
