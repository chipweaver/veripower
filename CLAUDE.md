# CLAUDE.md — VeriPower Plugin

AI-assisted IC design flow. Provides a stage-gated pipeline from specification
through power-analysis, with each stage as a standalone skill, closed by the
ask-gated `kernel.py signoff` verb.

## Pipeline

Signoff is not a stage: with every proof valid and every oracle pinned, a human closes
the module with `kernel.py signoff`. See "Kernel & Skill Dispatch" below.

The dependency graph is DERIVED from each rule's artifact input/output selectors —
no separate stage DAG is maintained. Failure routing is computed by `kernel.py decide`
(reading each failing envelope's own `fix_owner`); a simulation failure it could not attribute dispatches `simulation-triage`,
whose reap lands a `diagnosis` event. Authoritative registry and routing rules:
`framework/scripts/rules.py:RULES`.

## Module Layout

Per-module work tree under the module directory `--module` names (conventionally `asic/<module>/`, but the kernel layers no convention on the path it is given):

- `events.jsonl` — append-only event log, the SOLE durable state file (6 event types: `dispatch`, `outcome`, `diagnosis`, `pin`, `reopen`, `signoff`; schemas `framework/references/schemas/events/`). Written only by `kernel.py`; per-stage status is derived from it + disk fingerprints on demand (`kernel.py status`), never stored.
- `Design/rtl-design/semantic-review/` — the intent review of the delivered RTL against its design intent, written by fresh reviewers (contract `skills/rtl-design/references/rtl-review-task-contract.md`); how the wave splits the RTL across files is the stage's call, and the directory is delivered and endorsed whole, so that call costs the kernel nothing. rtl-design's proposed oracle, prose rather than a verdict.
- `Verification/simulation/conformance-review.md` — per-testpoint check-adequacy review, written by simulation's own Level-1 reviewer: prose per finding, with `BLOCKING` on the heading of one that stops the round. Unlike the other stages' reviews it is not an oracle and no human reads it before the stage routes on it, so that one marker is the whole machine-readable part and a trip is dispositioned in-stage; the promoted review itself is what survives that.
- `Verification/simulation-plan/plan-review/review.md` + `decisions.md` — testpoint-adequacy review, written by simulation-plan's self-dispatched Level-1 reviewer (prose: what it compared against, whether it blocks, where); `decisions.md` records the user's per-finding resolution at its human gate. Simulation-plan's proposed oracle — the kernel fingerprints it, no script reduces it to a verdict.
- `intent/` (module root) — the intent tree, the engineer's container: `brainstorm.md` in any shape, plus whatever they delivered with it and the document names as authoritative (a reference model, a register map, a standard). Its internal layout is not regulated. The pre-pipeline `brainstorm` skill (own session) is one way to write the document. Frozen for the run, NOT listed in specification's `result.json.artifacts[]`. Every rule binds it by the `intent` key, which resolves to the container itself, so what a stage is handed is exactly what its proof records — one merkle over the directory; `intent/brainstorm.md` must exist for anything to be dispatchable. Anything else at the module root is not intent: no stage is handed it and no proof records it. The document is read whole only by specification, another file in the container by whoever a requirement row pointing at it concerns.
- `Design/specification/requirements.json` — the requirements ledger: one row per proposition the intent document states, in the engineer's words, with `judge` naming who establishes it (a stage, `human`, `outside`, `none`) and, when the bound is in a unit a tool reports, a `target`. Every downstream rule binds it; scripts act on `id` / `judge` / `target`, readers on `verbatim`. Schema `skills/specification/references/requirements.schema.json`.
- `Design/specification/manifest.json` — child registry SSoT (every module, N≥1; contains `module` and `children[]` with `name` / `doc` / `rtl_modules[]`).
- `Design/specification/spec-review/` — the module-level review of the ledger against the intent document (`requirements.md`), the per-child reviews of each child design against the ledger, and `decisions.md`, the user's rulings at both gates. Prose: what it compared against, whether it blocks, where. Specification's proposed oracle — the kernel fingerprints it, no script reduces it to a verdict.
- `Design/specification/children/` — the per-child sub-designs (frontmatter `ports` / `clocks` + §1–§5; §5 points into `check-hints/`, whose entries name the ledger rows each check establishes).

Result-envelope schemas: `framework/references/schemas/`.

Domain-specific coding rules live in each skill's references.

## Kernel & Skill Dispatch

- `framework/scripts/kernel.py` — the kernel CLI, the SOLE writer of `events.jsonl` (9 verbs: `decide`, `dispatch`, `reap`, `diagnose`, `pin`, `reopen`, `signoff`, `status`, `consequences`; flags via `kernel.py <verb> --help`). The `design-flow` Orchestrator loops `decide` → execute the one returned action.
- `kernel.py pin` / `reopen` / `signoff` are **ask-gated judgment verbs** — proposed only on explicit human intent; the harness permission gate prompts the user on every call. `pin`/`reopen` ratchet a `proposed` (LLM-authored) oracle to `human` grade and back; `signoff` closes the module once `facts.signoff_gate` is clear, and returns `facts.signoff_basis` — per proof, the oracle's live grade, the fingerprint a `human` pin named, the reap-time tool identity, and the input set — so the act records which proposition was endorsed, not just that it was. Together they are the signoff trust boundary.
- `framework/scripts/rules.py` — the rule registry SSoT (`RULES`, `FORWARD_PRIORITY`, `PIPELINE_INPUTS`, `ADVISORY_ORDER`); the dependency graph is derived from rules' artifact selectors (`producer_of` / `input_producers` / `input_closure`).
- `framework/scripts/facts.py` — event-log I/O, content fingerprints, and the freshness queries (`proof_valid`, `input_available`, `projection`), plus the strictest of them: `signoff_gate` (the 3-condition trust boundary) and `signed_off`. Validity is a query over the log + disk, never a stored bit.
- `framework/scripts/schedule.py` — the scheduler (`decide`): pure over (disk, log, args), exactly one action per call. The goal set is derived from the log — the currently-failing proofs, or all eight when none are failing — so nothing is carried between turns; `--closing` arms the signoff gate at `DONE` without changing which proofs are required.
- `framework/scripts/store.py` — artifact-lifecycle internals (promote, trace mirroring, dispatch-time `dispatch.json` authoring via `write_dispatch`, author self-carry via `carry_self`), imported by `kernel.py`; internal — never invoked directly.
- Main-thread-loaded stages: `specification`, `simulation-plan`, `rtl-design`, and `simulation` — the Orchestrator loads them into its own context. The other 4 stages (`lint-cdc`, `synthesis`, `timing-analysis`, `power-analysis`) plus `simulation-triage` load into a fresh Task subagent's; branch on the `DISPATCH` action's `execution` field. See `skills/design-flow/SKILL.md`.
- `brainstorm` is a separate **pre-pipeline** skill (own session, NOT in the orchestrator-dispatch list above): it runs the requirements dialogue and writes `intent/brainstorm.md`, one way to produce the intent document the pipeline starts from. It writes no `result.json` and calls no `kernel.py`.
- `env-precheck` is likewise **pre-pipeline** (own session, NOT orchestrator-dispatched, no rule, no `result.json`, no `kernel.py`): it checks `docs/eda-env.md`'s requirements against the live machine and smoke-runs each license checkout, reporting which stages are runnable. Nothing in the pipeline depends on it having run — an unmet environment still surfaces as a stage `blocked`.

## Reference Docs

- `ARCHITECTURE.md` — the event-sourced kernel: the pipeline and its derived dependency graph, proof validity, failure attribution, the trust boundary, and what the system does not do
- `CONTRIBUTING.md` — contribution + skill-authoring conventions
- `docs/eda-env.md` — EDA tool / license / OS environment requirements (deployment-time)
