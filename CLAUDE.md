# CLAUDE.md — VeriPower Plugin

AI-assisted IC design flow for Claude Code. Provides a stage-gated pipeline
from specification through power-analysis, with each stage as a standalone skill,
closed by the ask-gated `kernel.py signoff` verb.

## Pipeline

Signoff is not a stage: with every proof valid and every oracle pinned, a human closes
the module with `kernel.py signoff` (§5.5). See "Kernel & Skill Dispatch" below.

The dependency graph is DERIVED from each rule's artifact input/output selectors —
no separate stage DAG is maintained. Failure routing is computed by `kernel.py decide`
(reading each failing envelope's own `fix_owner`); a simulation failure it could not attribute dispatches `simulation-triage`,
whose reap lands a `diagnosis` event. Authoritative registry and routing rules:
`framework/scripts/rules.py:RULES` / `ARCHITECTURE.md §3` (§5.4 failure routing).

## Module Layout

Per-module work tree under the module directory `--module` names (conventionally `asic/<module>/`, but the kernel layers no convention on the path it is given):

- `events.jsonl` — append-only event log, the SOLE durable state file (6 event types: `dispatch`, `outcome`, `diagnosis`, `pin`, `reopen`, `signoff`; schemas `framework/references/schemas/events/`). Written only by `kernel.py`; per-stage status is derived from it + disk fingerprints on demand (`kernel.py status`), never stored.
- `Design/rtl-design/semantic-review/*.md` — the intent review of the delivered RTL against its design intent, written by fresh reviewers (contract `skills/rtl-design/references/rtl-review-task-contract.md`); how the wave splits the RTL across files is the stage's call. rtl-design's proposed oracle, prose rather than a verdict.
- `Verification/simulation/conformance-review.md` — per-testpoint check-adequacy review, written by simulation's own Level-1 reviewer: prose per finding, with `BLOCKING` on the heading of one that stops the round. Unlike the other stages' reviews it is not an oracle and no human reads it before the stage routes on it, so that one marker is the whole machine-readable part and a trip is dispositioned in-stage; the promoted review itself is what survives that.
- `Verification/simulation-plan/plan-review/review.md` + `decisions.md` — testpoint-adequacy review, written by simulation-plan's self-dispatched Level-1 reviewer (prose: what it compared against, whether it blocks, where); `decisions.md` records the user's per-finding resolution at its human gate. Simulation-plan's proposed oracle — the kernel fingerprints it, no script reduces it to a verdict.
- `brainstorm.md` (module root) — sole upstream of `design.md`; produced by the pre-pipeline `brainstorm` skill (own session), frozen for the run, NOT listed in specification's `result.json.artifacts[]`. It needs only to exist: the kernel gates `specification` on that and nothing else.
- `Design/specification/manifest.json` — child registry SSoT (every module, N≥1; contains `module` and `children[]` with `name` / `doc` / `rtl_modules[]` / `brainstorm_anchor`).
- `Design/specification/ppa.json` — PPA targets emitted by specification; a declared input of `synthesis` and `power-analysis` (they read it themselves — nothing is injected into their prompts). `rtl-design` reads it too, from its own injected specification location.
- `Design/specification/spec-review/<child>.md × N` + `decisions.md` — per-child spec intent review, written by that child's reviewer (prose: what it compared against, whether it blocks, where); `decisions.md` records the user's per-finding resolution at the design.md gate. Specification's proposed oracle — the kernel fingerprints it, no script reduces it to a verdict.
- `Design/specification/<child>.md × N` — per-child sub-design (frontmatter + §1–§5 strong structure; §5 Verification Hints points to `check-hints/<child>.json`).

Result-envelope schemas: `framework/references/schemas/`.

Domain-specific coding rules live in each skill's references.

## Kernel & Skill Dispatch

- `framework/scripts/kernel.py` — the kernel CLI, the SOLE writer of `events.jsonl` (9 verbs: `decide`, `dispatch`, `reap`, `diagnose`, `pin`, `reopen`, `signoff`, `status`, `consequences`; flags via `kernel.py <verb> --help`). The `design-flow` Orchestrator loops `decide` → execute the one returned action.
- `kernel.py pin` / `reopen` / `signoff` are **ask-gated judgment verbs** — proposed only on explicit human intent; the harness permission gate prompts the user on every call. `pin`/`reopen` ratchet a `proposed` (LLM-authored) oracle to `human` grade and back; `signoff` closes the module once `facts.signoff_gate` is clear, and returns `facts.signoff_basis` — per proof, the oracle's live grade, the fingerprint a `human` pin named, the reap-time tool identity, and the input set — so the act records which proposition was endorsed, not just that it was. Together they are the signoff trust boundary.
- `framework/scripts/rules.py` — the rule registry SSoT (`RULES`, `FORWARD_PRIORITY`, `PIPELINE_INPUTS`, `ADVISORY_ORDER`); the dependency graph is derived from rules' artifact selectors (`producer_of` / `input_producers` / `input_closure`).
- `framework/scripts/facts.py` — event-log I/O, content fingerprints, and the freshness queries (`proof_valid`, `input_available`, `projection`), plus the strictest of them: `signoff_gate` (the 3-condition trust boundary) and `signed_off` (the §3.6 predicate). Validity is a query over the log + disk, never a stored bit.
- `framework/scripts/schedule.py` — the scheduler (`decide`): pure over (disk, log, args), exactly one action per call. The goal set is derived from the log — the currently-failing proofs, or all eight when none are failing — so nothing is carried between turns; `--closing` arms the signoff gate at `DONE` without changing which proofs are required.
- `framework/scripts/store.py` — artifact-lifecycle internals (promote, trace mirroring, dispatch-time `dispatch.json` authoring via `write_dispatch`, author self-carry via `carry_self`), imported by `kernel.py`; internal — never invoked directly.
- Main-thread-loaded stages: `specification`, `simulation-plan`, `rtl-design`, and `simulation` — Orchestrator calls `Skill(veripower:...)` directly. The other 4 stages (`lint-cdc`, `synthesis`, `timing-analysis`, `power-analysis`) plus `simulation-triage` are strictly Task-dispatched subagents; branch on the `DISPATCH` action's `execution` field. See `skills/design-flow/SKILL.md` and `ARCHITECTURE.md §2`.
- `brainstorm` is a separate **pre-pipeline** skill (own session, NOT in the orchestrator-dispatch list above): it runs the D0–D7 dialogue and produces the `brainstorm.md` the pipeline starts from. It writes no `result.json` and calls no `kernel.py`.

## Reference Docs

- `ARCHITECTURE.md` — the event-sourced kernel: rule registry + derived dependency graph, proof validity, scheduling, trust boundary
- `CONTRIBUTING.md` — contribution + skill-authoring conventions
- `docs/eda-env.md` — EDA tool / license / OS environment requirements (deployment-time)
