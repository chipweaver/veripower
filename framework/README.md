# `framework/` — VeriPower Plugin Framework Layer

A directory guide: what lives here, who consumes it, and what must not be put
here. Protocol *semantics* (the kernel verb surface, the event types, proof
validity, scheduling) are specified once in the project architecture document and
deliberately not restated below, so that this file cannot drift from them.

This directory is the **framework layer** of the VeriPower plugin: the protocol,
schemas, and CLI tooling that the stage skills and orchestrator both work against.
It sits one layer above `skills/`; every skill produces or consumes artifacts
defined here, but no skill *owns* this layer.

> **Why "framework" and not "shared"?** "Shared" implied "multi-consumer", yet
> most of the items below have `design-flow` (the Orchestrator, driving `kernel.py`)
> as their primary caller. They belong here for a different reason: they are the
> **infrastructure** that defines what every skill, and the orchestrator, plugs into.

## What lives here

| Path | What it is | Primary consumer | Available to |
|---|---|---|---|
| `references/schemas/envelope.schema.json` | The cross-stage `result.json` envelope that every stage's own `result.schema.json` composes by JSON Schema `$ref`, carrying the universal fields any reader can rely on regardless of which stage produced the file. Genuinely cross-stage: every producer references it, every consumer validates against it. | anyone reading a `result.json` | all skills, orchestrator, tests |
| `references/schemas/events/` | One schema file per `asic/<module>/events.jsonl` event type: the audit-log contract. Events are written by `kernel.py` alone and validated against these at append time, and are readable by anyone debugging or auditing a run, not just the writer. | `kernel.py` | all consumers of `events.jsonl` |
| `references/prompts/stage-subagent.md.tpl` | The prompt template the orchestrator renders when dispatching a stage subagent. Defines the canonical injection points every stage skill documents in its SKILL.md input table. | `design-flow`, as renderer | designers studying the protocol |
| `scripts/kernel.py` | The kernel CLI and the sole writer of `events.jsonl`. Not a private library imported by one skill: a project CLI runnable by humans driving a pipeline manually, by tests, and by CI. | `design-flow` | tests, manual operators |
| `scripts/rules.py` | The rule registry SSoT (`RULES`, `FORWARD_PRIORITY`, `PIPELINE_INPUTS`, `ADVISORY_ORDER`). One `Rule` is one kernel-scheduled unit, and the producer-consumer dependency graph is derived from each rule's artifact selectors rather than maintained as a separate stage-view DAG. Dependency-light leaf, bare-importable. | `kernel.py`, `facts.py`, `schedule.py`, by import | tests, anyone importing the registry |
| `scripts/facts.py` | Event-log I/O, content fingerprints, and the freshness queries built on them. Owns nothing mutable: every answer is computed from the log plus disk on demand, never stored as a bit. | `kernel.py`, `schedule.py`, by import | tests, anyone reading `events.jsonl` |
| `scripts/schedule.py` | The scheduler behind the `decide` verb: objective-scoped, pure over (disk, log, args), returning exactly one action per call. Also owns the fresh-failure disposition — a failure is attributed by its own envelope, and this file only checks that naming is legal. Import-only, reached solely through `kernel.py`. | `kernel.py`, by import | internal, tests |
| `scripts/store.py` | Filesystem artifact-lifecycle helpers: dispatch-time input injection and author self-carry, reap-time promote and canonical-view rebuild. An import-only internal with a single caller. | `kernel.py`, by import | internal only |

Invocation contract for the CLI: the command lines and flags come from
`kernel.py <verb> --help`, and every verb prints a JSON envelope.

## What does NOT belong here

- Per-stage logic, schemas, or templates. Those live in `skills/<stage>/`.
- Skill-private constants. Those live in `skills/<stage>/references/`.
- Project-wide documentation and design rationale. Those live at the top level and under `docs/`.
- A second copy of protocol semantics the architecture document owns: verb inventories, event-type inventories, validity rules, module-internal behavior. Two copies of a volatile fact drift, and the copy that drifts is the one nobody tests.

## Relationship to `skills/`

`skills/` contains the *components*, meaning the stage skills plus the
orchestrator; `framework/` contains the *protocol* those components implement.
Adding a stage touches this layer in exactly one place: registering that stage's
`Rule` in `scripts/rules.py`, whose artifact selectors are what the dependency
graph is derived from. Everything else the stage needs, including the
`result.schema.json` that `$ref`s the envelope here, lives under its own skill
directory.

No changes to `framework/` should ever be made in service of a single skill's
private needs; those go under that skill's own directory.
