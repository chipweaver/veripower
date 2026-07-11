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

The dependency graph is DERIVED from each rule's artifact input/output selectors —
no separate stage DAG is maintained. Failure routing is computed by `kernel.py decide`
(composing `route.py`); ambiguous simulation failures dispatch `simulation-triage`,
whose reap lands a `diagnosis` event. Authoritative registry and routing rules:
`framework/scripts/rules.py:RULES` / `ARCHITECTURE.md §3` (§5.4 failure routing).

## Module Layout

Per-module work tree under `asic/<module>/`:

- `events.jsonl` — append-only event log, the SOLE durable state file (7 event types: `dispatch`, `outcome`, `diagnosis`, `epoch`, `pin`, `reopen`, `escalation`; schemas `framework/references/schemas/events/`). Written only by `kernel.py`; per-stage status is derived from it + disk fingerprints on demand (`kernel.py status`), never stored.
- `Design/<stage>/result.json` — for specification, rtl-design, lint-cdc, synthesis, timing-analysis
- `Design/rtl-design/semantic-review.json` — gating per-child intent-review produced by rtl-design's Step-4.4 semantic gate (schema `skills/rtl-design/references/semantic-review.schema.json`).
- `Verification/<stage>/result.json` — for simulation-plan, simulation, power-analysis, simulation-triage
- `Verification/simulation/conformance-review.json` — gating per-testpoint check-adequacy review produced by the simulation stage's Step-4 conformance gate (schema `skills/simulation/references/conformance-review.schema.json`); promoted advisory artifact, gate source for `failure_phase=conformance`.
- `Verification/simulation-plan/plan-review.json` — gating testpoint-adequacy review (`coverage` vs spec blocks; `adequacy` check-strategy soundness is advisory must-acknowledge) produced by simulation-plan's Step-4 adequacy gate via a self-dispatched Level-1 reviewer (schema `skills/simulation-plan/references/plan-review.schema.json`).
- `frontend-signoff/result.json` — terminal signoff
- `brainstorm.md` (module root, `asic/<module>/brainstorm.md`) — sole upstream of `design.md`; produced by the pre-pipeline `brainstorm` skill (own session), frozen for the run, NOT listed in specification's `result.json.artifacts[]`.
- `Design/specification/manifest.json` — child registry SSoT (every module, N≥1; contains `module`, `children[]` with `name` / `doc` / `rtl_modules[]` / `brainstorm_anchor` / `role`, and optional `shared_subsections[]`).
- `Design/specification/coverage.json` — script-generated coverage, by the `spec` package's `check-coverage` verb (sub-blocks documented in `specification/SKILL.md`). The `spec` `derive-constraints` verb generates `constraints/<TOP>.{sdc,sgdc}`.
- `Design/specification/ppa.json` — PPA targets emitted by specification; a declared input of `synthesis` and `power-analysis` (they read it themselves — nothing is injected into their prompts). `rtl-design` gets targets only via its Orchestrator-authored directive.
- `Design/specification/spec-review.json` — gating per-child spec intent review (`faithfulness` vs brainstorm blocks; `conformance` vs the §1.4.x pinned Encoding + §1.4.2.1 inter-module behavior contract (encoding decode/adequacy + behavior-contract name-resolution) blocks; `soundness` — micro-arch realizability + observed cross-interface inconsistency — is advisory must-acknowledge) produced by specification's Step-7 semantic gate (schema `skills/specification/references/spec-review.schema.json`).
- `Design/specification/<child>.md × N` — per-child sub-design (frontmatter + §1–§5 strong structure including 9-column §5 Verification Hints).

Result-envelope schemas: `framework/references/schemas/`.

## Path Variables

- `${CLAUDE_PLUGIN_ROOT}` — VeriPower plugin root
- `${CLAUDE_SKILL_DIR}` — current skill directory

Domain-specific coding rules live in each skill's references.

## Kernel & Skill Dispatch

- `framework/scripts/kernel.py` — the kernel CLI, the SOLE writer of `events.jsonl` (10 verbs: `decide`, `dispatch`, `reap`, `diagnose`, `escalate`, `epoch`, `pin`, `reopen`, `status`, `consequences`; flags via `kernel.py <verb> --help`). The `design-flow` Orchestrator loops `decide` → execute the one returned action.
- `kernel.py pin` / `reopen` are **ask-gated judgment verbs** — proposed only on explicit human intent; the harness permission gate prompts the user on every call. They ratchet a `proposed` (LLM-authored) oracle to `human` grade and back — the signoff trust boundary.
- `framework/scripts/rules.py` — the rule registry SSoT (`RULES`, `FORWARD_PRIORITY`, `PIPELINE_INPUTS`, `ADVISORY_ORDER`); the dependency graph is derived from rules' artifact selectors (`producer_of` / `input_producers` / `input_closure`).
- `framework/scripts/facts.py` — event-log I/O, content fingerprints, and the freshness queries (`proof_valid`, `input_available`, `projection`). Validity is a query over the log + disk, never a stored bit.
- `framework/scripts/schedule.py` — the scheduler (`decide`): objective-scoped (`delivery`/`repair`/`signoff`), pure over (disk, log, args), exactly one action per call.
- `framework/scripts/route.py` — pure deterministic rework-target selection (sole home of the failure→target maps); composed inside `schedule.py` and `kernel.py`. No state.
- `framework/scripts/store.py` — artifact-lifecycle internals (promote, trace mirroring), imported by `kernel.py`; internal — never invoked directly.
- Main-thread-loaded stages: `specification`, `simulation-plan`, `rtl-design`, and `simulation` — Orchestrator calls `Skill(veripower:...)` directly. The other 5 stages (`lint-cdc`, `synthesis`, `timing-analysis`, `power-analysis`, `frontend-signoff`) plus `simulation-triage` are strictly Task-dispatched subagents; branch on the `DISPATCH` action's `execution` field. See `skills/design-flow/SKILL.md` and `ARCHITECTURE.md §2`.
- `brainstorm` is a separate **pre-pipeline** skill (own session, NOT in the orchestrator-dispatch list above): it runs the D0–D7 dialogue and produces the approved `brainstorm.md` the pipeline starts from. It writes no `result.json` and calls no `kernel.py`.

## Reference Docs

- `ARCHITECTURE.md` — the event-sourced kernel: rule registry + derived dependency graph, proof validity, scheduling, trust boundary
- `CONTRIBUTING.md` — contribution + skill-authoring conventions
- `docs/eda-env.md` — EDA tool / license / OS environment requirements (deployment-time)
