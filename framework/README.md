# `framework/` — VeriPower Plugin Framework Layer

A directory guide: what lives here and who consumes it. Protocol *semantics*
(proof validity, failure attribution, the trust boundary) are described in
[ARCHITECTURE.md](../docs/ARCHITECTURE.md).

This directory is the **framework layer** of the VeriPower plugin: the protocol,
schemas, and CLI tooling that the stage skills and orchestrator both work against.
Stage skills use its dispatch and result interfaces; `design-flow` uses its
commands to coordinate their work.

## What lives here

| Path | What it is | Primary consumer | Available to |
|---|---|---|---|
| `references/schemas/envelope.schema.json` | The cross-stage `result.json` envelope that every stage's own `result.schema.json` composes by JSON Schema `$ref`, carrying the universal fields any reader can rely on regardless of which stage produced the file. | anyone reading a `result.json` | all skills, orchestrator, tests |
| `references/schemas/events/` | Schemas used to validate event records before appending to `<module-dir>/events.jsonl`. | `store.py` | all consumers of `events.jsonl` |
| `references/prompts/stage-subagent.md.tpl` | The prompt template for a stage subagent. Directs the executor to its skill and the workdir's `dispatch.json` for inputs and task context. | `design-flow`, as renderer | designers studying the protocol |
| `scripts/kernel.py` | CLI entry point: validates commands, derives outcomes and coordinates module updates through storage operations. | `design-flow` | tests, manual operators |
| `scripts/rules.py` | Stage declarations and the producer graph derived from artifact inputs. | `kernel.py`, `facts.py`, `schedule.py`, `store.py` | tests, anyone importing the registry |
| `scripts/facts.py` | Read-only event queries, content fingerprints, proof validity, input availability and signoff readiness. | `kernel.py`, `schedule.py` | internal, tests |
| `scripts/schedule.py` | Selects one action from current facts, unresolved repairs, dependencies and execution order. | `kernel.py` | internal, tests |
| `scripts/store.py` | Event-log I/O, schema validation, input protection, dispatch handoff, author carry and artifact publication. | `kernel.py`, `facts.py`, `schedule.py` | internal, tests |

Start with `kernel.main` for commands, `schedule.decide` for action selection,
`facts.proof_valid` for validity, and `store.promote` for publication.
`rules.RULES` defines the stages and their artifact inputs.

Command lines and flags come from `kernel.py <verb> --help`. Commands return JSON.
A refused operation can return `ok: false` with exit status 0; callers must inspect
the response as well as the process status. Argument parsing and execution errors
can instead exit nonzero with a message on stderr. A blocked reap includes its
reason in both the response and the recorded outcome.

## Related locations

- Per-stage logic, schemas, or templates. Those live in `skills/<stage>/`.
- Skill-private constants. Those live in `skills/<stage>/references/`.
- Project-wide documentation and design rationale. Those live at the top level and under `docs/`.
- Protocol semantics: verb inventories (`kernel.py <verb> --help`), event-type inventories (their schemas under `references/schemas/events/`), validity rules and module-internal behavior (the architecture document).

## Relationship to `skills/`

Stage-specific instructions, scripts and result schemas live under `skills/`.
Adding a stage requires a `Rule` in `scripts/rules.py`; its artifact selectors
determine dependencies. A forward pipeline stage also belongs in `FORWARD_PRIORITY`.
Check consumers of stage names, including the shared result envelope's `stage`
enum and the specification's requirement `judge` enum, along with the cross-stage
contract tests.
