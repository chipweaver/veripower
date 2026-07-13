# `framework/` — VeriPower Plugin Framework Layer

This directory is the **framework layer** of the VeriPower plugin: the protocol,
schemas, and CLI tooling that the stage skills and orchestrator both work against.
It sits one layer above `skills/` — every skill produces or consumes artifacts
defined here, but no skill *owns* this layer.

> **Why "framework" and not "shared"?** "Shared" implied "multi-consumer" — but
> most of the items below have `design-flow` (the Orchestrator, driving `kernel.py`)
> as their primary caller, and they belong here for a different reason: they're the
> **infrastructure** that defines what every skill (and the orchestrator) plugs into.

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
type: `dispatch`, `outcome`, `diagnosis`, `pin`, `reopen`, `escalation`).
Events are written by `kernel.py` — the sole state file, no `task.json` snapshot —
and **readable by anyone debugging or auditing a pipeline run** — not just the
writer.

### `references/prompts/stage-subagent.md.tpl` — dispatcher prompt template

The prompt template the orchestrator renders when dispatching a stage subagent.
Defines the canonical injection points (`{workdir}`, `{module}`,
`{failing_result}`, `{directive_path}`) that every stage skill
documents in its SKILL.md input table.

### `scripts/kernel.py` — the kernel CLI

The SOLE writer of `events.jsonl`. Nine verbs: `decide`, `dispatch`, `reap`,
`diagnose`, `escalate`, `pin`, `reopen`, `status`, `consequences`
(flags via `kernel.py <verb> --help`). The `design-flow` Orchestrator loops
`decide` → execute the one returned action.

The tool is **runnable by anyone**: humans manually driving a pipeline, tests,
CI, future automated runners. Not a private library imported by one skill — a
project CLI that implements the protocol the framework defines.

### `scripts/rules.py` — the rule registry SSoT

`RULES`, `FORWARD_PRIORITY`, `PIPELINE_INPUTS`, `ADVISORY_ORDER`. One `Rule` =
one kernel-scheduled unit; the dependency graph is DERIVED from rules' artifact
input/output selectors (`producer_of` / `input_producers` / `input_closure`) — no
separate stage-view DAG is maintained. Dependency-light leaf, bare-importable.

### `scripts/facts.py` — event-log I/O and freshness queries

Event-log I/O, content fingerprints, and the freshness queries (`proof_valid`,
`input_available`, `projection`). Validity is a query over the log + disk,
computed on demand — never a stored bit.

### `scripts/schedule.py` — the scheduler

Implements `kernel.py decide`: objective-scoped (`delivery`/`repair`/`signoff`),
pure over (disk, log, args), returns exactly one action per call. Composes
`route.py` for self-describing-failure attribution. Import-only — reached
solely through `kernel.py`.

### `scripts/route.py` — deterministic rework-target router

The sole home of the failure→target maps: a pure, stateless evaluator that maps a
self-describing stage failure to a rework target (or to `ESCALATE`). Composed
unchanged inside `schedule.py` and `kernel.py` — an import-only internal, never
invoked directly. Holds no state. (Ambiguous simulation failures are not routed
here — schedule dispatches `simulation-triage`; the `TRIAGE_ROOT_CAUSE` map is
consumed by `kernel._derive_triage`, and the reliability gate by `schedule._reliable`.)

### `scripts/store.py` — artifact-lifecycle internals

The promote + trace-mirroring helpers imported by `kernel.py` (canonical-view
rebuild, hardlink promote, async-transcript mirroring). An import-only internal —
`kernel.py` is its only caller; never invoked directly.

## Ownership model

| Item | Producer | Primary consumer | Available to |
|---|---|---|---|
| `envelope.schema.json` | Stage skills (via $ref) | Anyone reading `result.json` | All skills + orchestrator + tests |
| `events/*.schema.json` | `kernel.py` | `kernel.py` + auditors | All consumers of `events.jsonl` |
| `stage-subagent.md.tpl` | n/a (template) | `design-flow` (renderer) | Designers studying the protocol |
| `kernel.py` | n/a (binary) | `design-flow` | tests / manual operators |
| `rules.py` | n/a (constants) | `kernel.py` + `facts.py` + `schedule.py` (import) | tests / anyone importing the registry |
| `facts.py` | n/a (library) | `kernel.py` + `schedule.py` (import) | tests / anyone reading events.jsonl |
| `schedule.py` | n/a (internal) | `kernel.py` (import, `decide` verb) | internal / tests |
| `route.py` | n/a (pure fn) | `schedule.py` + `kernel.py` (import) | internal / tests |
| `store.py` | n/a (internal) | `kernel.py` (import) | internal only |

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
3. Add itself as a `Rule` to `RULES` in `framework/scripts/rules.py`, declaring its
   artifact input/output selectors — the dependency graph is derived from these,
   there is no separate DAG to update.

No changes to `framework/` should ever be made in service of a single skill's
private needs — those go under that skill's own directory.
