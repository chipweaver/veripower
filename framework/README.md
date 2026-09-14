# `framework/` — VeriPower Plugin Framework Layer

A directory guide: what lives here and who consumes it. Protocol *semantics*
(proof validity, failure attribution, the trust boundary) are described in
[ARCHITECTURE.md](../ARCHITECTURE.md).

This directory is the **framework layer** of the VeriPower plugin: the protocol,
schemas, and CLI tooling that the stage skills and orchestrator both work against.
It sits one layer above `skills/`; every skill produces or consumes artifacts
defined here, but no skill *owns* this layer.

## What lives here

| Path | What it is | Primary consumer | Available to |
|---|---|---|---|
| `references/schemas/envelope.schema.json` | The cross-stage `result.json` envelope that every stage's own `result.schema.json` composes by JSON Schema `$ref`, carrying the universal fields any reader can rely on regardless of which stage produced the file. | anyone reading a `result.json` | all skills, orchestrator, tests |
| `references/schemas/events/` | Schemas used to validate event records before appending to `<module-dir>/events.jsonl`. | `store.py` | all consumers of `events.jsonl` |
| `references/prompts/stage-subagent.md.tpl` | The prompt template the orchestrator renders when dispatching a stage subagent. Defines the canonical injection points every stage skill documents in its SKILL.md input table. | `design-flow`, as renderer | designers studying the protocol |
| `scripts/kernel.py` | CLI entry point: validates commands, derives outcomes and coordinates module updates through storage operations. | `design-flow` | tests, manual operators |
| `scripts/rules.py` | Stage declarations and the producer graph derived from artifact inputs. | `kernel.py`, `facts.py`, `schedule.py`, `store.py` | tests, anyone importing the registry |
| `scripts/facts.py` | Read-only event queries, content fingerprints, proof validity, input availability and signoff readiness. | `kernel.py`, `schedule.py` | internal, tests |
| `scripts/schedule.py` | Selects one action from current facts, unresolved repairs, dependencies and execution order. | `kernel.py` | internal, tests |
| `scripts/store.py` | Event-log I/O, schema validation, input protection, dispatch handoff, author carry and artifact publication. | `kernel.py`, `facts.py`, `schedule.py` | internal, tests |

Start with `kernel.main` for commands, `schedule.decide` for action selection,
`facts.proof_valid` for validity, and `store.promote` for publication.
`rules.RULES` defines the stages and their artifact inputs.

Command lines and flags come from `kernel.py <verb> --help`. Commands return JSON;
errors that prevent execution are reported on stderr. A blocked reap includes its
reason in both the response and the recorded outcome.

## Related locations

- Per-stage logic, schemas, or templates. Those live in `skills/<stage>/`.
- Skill-private constants. Those live in `skills/<stage>/references/`.
- Project-wide documentation and design rationale. Those live at the top level and under `docs/`.
- Protocol semantics: verb inventories (`kernel.py <verb> --help`), event-type inventories (their schemas under `references/schemas/events/`), validity rules and module-internal behavior (the architecture document).

## Relationship to `skills/`

`skills/` contains the *components*, meaning the stage skills plus the
orchestrator; `framework/` contains the *protocol* those components implement.
Adding a stage touches this layer in exactly one place: registering that stage's
`Rule` in `scripts/rules.py`, whose artifact selectors are what the dependency
graph is derived from. Everything else the stage needs, including the
`result.schema.json` that `$ref`s the envelope here, lives under its own skill
directory.
