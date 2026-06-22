# CLAUDE.md — VeriPower Plugin

AI-assisted IC design flow for Claude Code. Provides a stage-gated pipeline
from specification through frontend-signoff, with each stage as a standalone skill.

## Pipeline

```
[brainstorm] (pre-pipeline, own session) → approved brainstorm.md ↓

[specification] → [simulation-plan] → [rtl-design]
                                            │
                          ┌─────────────────┴──────────────────┐
                          ↓                                    ↓
                     [lint-cdc]                          [simulation]
                          │                                    │
                          ↓                                    │
                     [synthesis]                               │
                          │                                    │
                          ↓                                    │
                  [timing-analysis]                            │
                          │                                    │
                          └─────────────────┬──────────────────┘
                                            ↓
                                    [power-analysis]
                                            │
                                            ↓
                                    [frontend-signoff]
```

Rework edges are routed by the `design-flow` Orchestrator; simulation failures
route through `simulation-triage` for root-cause clustering. Authoritative DAG
and failure-routing rules: `ARCHITECTURE.md §3` (§5.4 failure routing) /
`framework/scripts/topology.py:PREREQ_OF`.

## Module Layout

Per-module work tree under `asic/<module>/`:

- `task.json` — current stage state
- `events.jsonl` — append-only event log
- `Design/<stage>/result.json` — for specification, rtl-design, lint-cdc, synthesis, timing-analysis
- `Design/rtl-design/semantic-review.json` — gating per-child intent-review produced by rtl-design's Step-4.4 semantic gate (schema `skills/rtl-design/references/semantic-review.schema.json`).
- `Verification/<stage>/result.json` — for simulation-plan, simulation, power-analysis
- `Verification/simulation/conformance-review.json` — gating per-testpoint check-adequacy review produced by the simulation stage's Step-4 conformance gate (schema `skills/simulation/references/conformance-review.schema.json`); promoted advisory artifact, gate source for `failure_phase=conformance`.
- `Verification/simulation-plan/plan-review.json` — gating testpoint-adequacy review (`coverage` vs spec blocks; `adequacy` check-strategy soundness is advisory must-acknowledge) produced by simulation-plan's Step-3.5 adequacy gate via a self-dispatched Level-1 reviewer (schema `skills/simulation-plan/references/plan-review.schema.json`).
- `frontend-signoff/result.json` — terminal signoff
- `brainstorm.md` (module root, `asic/<module>/brainstorm.md`) — sole upstream of `design.md`; produced by the pre-pipeline `brainstorm` skill (own session), frozen for the run, NOT listed in specification's `result.json.artifacts[]`.
- `Design/specification/manifest.json` — child registry SSoT (every module, N≥1; contains `module`, `children[]` with `name` / `doc` / `rtl_modules[]` / `brainstorm_anchor` / `role`, and optional `shared_subsections[]`).
- `Design/specification/coverage.json` — script-generated coverage, by `skills/specification/scripts/check_coverage.py` (sub-blocks documented in `specification/SKILL.md`). `skills/specification/scripts/derive_constraints.py` generates `constraints/<TOP>.{sdc,sgdc}`.
- `Design/specification/spec-review.json` — gating per-child spec intent review (`faithfulness` vs brainstorm blocks; `soundness` — micro-arch realizability + observed cross-interface inconsistency — is advisory must-acknowledge) produced by specification's Step-6.5 semantic gate (schema `skills/specification/references/spec-review.schema.json`).
- `Design/specification/<child>.md × N` — per-child sub-design (frontmatter + §1–§5 strong structure including 9-column §5 Verification Hints).

Result-envelope schemas: `framework/references/schemas/`.

## Path Variables

- `${CLAUDE_PLUGIN_ROOT}` — VeriPower plugin root
- `${CLAUDE_SKILL_DIR}` — current skill directory

Domain-specific coding rules live in each skill's references.

## State Tool & Skill Dispatch

- `framework/scripts/state.py` — the state tool (commands via `state.py --help`). No routing logic — scheduling is computed by `orchestrate.py decide` (see below), which the `design-flow` Orchestrator executes.
- `framework/scripts/topology.py` — DAG structural SSoT (`FORWARD_PRIORITY`, `PREREQ_OF`, `eligible()`); `state.py` imports the subset it uses (so those names also resolve as `state.X`), while `orchestrate.py` imports `topology` directly.
- `framework/scripts/orchestrate.py` — the decider (`orchestrate.py decide`); reads on-disk state and returns exactly one action per call; the Orchestrator is a thin executor of it.
- `framework/scripts/route.py` — pure deterministic rework-target selection (sole home of the failure→target maps); composed unchanged inside `orchestrate.py`. No state.
- `framework/scripts/artifacts.py` — artifact-lifecycle internals (promote, trace mirroring), imported by `state.py`; internal — never invoked directly.
- Main-thread-loaded stages: `specification`, `simulation-plan`, `rtl-design`, and `simulation` — Orchestrator calls `Skill(veripower:...)` directly. The other 5 stages (`lint-cdc`, `synthesis`, `timing-analysis`, `power-analysis`, `frontend-signoff`) are strictly Task-dispatched subagents. See `skills/design-flow/SKILL.md` and `ARCHITECTURE.md §2`.
- `brainstorm` is a separate **pre-pipeline** skill (own session, NOT in the orchestrator-dispatch list above): it runs the D0–D7 dialogue and produces the approved `brainstorm.md` the pipeline starts from. It writes no `result.json` and calls no `state.py`.

## Reference Docs

- `ARCHITECTURE.md` — pipeline DAG, rework edges, design rationale
- `CONTRIBUTING.md` — contribution + skill-authoring conventions
- `docs/eda-env.md` — EDA tool / license / OS environment requirements (deployment-time)
