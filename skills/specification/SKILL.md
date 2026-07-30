---
name: specification
description: Use when writing or reviewing design specification (design.md), defining interfaces or constraints (SDC/SGDC), or updating from rework feedback; not for RTL implementation or verification.
---

# Requirements and Specification Freeze

Your sole responsibility: derive a frozen design source of truth from an approved `<brainstorm>/brainstorm.md` — `design.md` (overview §1.1–1.6 + §1.7 submodule index) + per-child `<child>.md` + `manifest.json` + `ppa.json` + `clocks.json` + `features.json` + `top-io.json` + `interconnects.json` + `check-hints/<child>.json` + a pair of constraint files (`<TOP>.sdc` / `<TOP>.sgdc`). You are a thin Level-0 dispatcher: three sub-agent waves, two path-handoff gates, deterministic main-thread scripts in between; the brainstorm dialogue lives in the pre-pipeline `brainstorm` skill.

## Iron Rule

Your boundary:

- **Write only under `{workdir}`** (artifacts + `result.json`); never touch another module's artifacts. Reading templates and upstream inputs outside is fine.
- **No brainstorm here.** Consume the frozen, approved `brainstorm.md`; run the two path-handoff gates, but hold no document body and drive no D0–D7 dialogue.
- **No LLM constraint overlay.** `derive-constraints` generates and self-checks the constraint files; you neither hand-write nor re-check them.
- **`design.md` carries no by-reference jumps** (`see brainstorm`, `see spec D`, …): it is the unique source of truth, so inline every referenced passage verbatim.
- **Reference PPA targets by pointing at `ppa.json`, never by restating the numbers**: this is the one sanctioned by-reference pointer (brainstorm content is still inlined verbatim).
- **`manifest.json` is read-only after the partition gate**; changing N takes a fresh run.
- **Minimal change on re-dispatch**: with a prior `design.md` on disk, touch only what the round requires and leave every other file byte-identical.
- **Scripts are black boxes**: invoke them per the documented commands and act on their documented failure output. Read the source only to debug a suspected script bug — a verdict you re-derive by reading the code is your own judgment wearing the gate's name.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |

### External reference inputs

Read `{workdir}/dispatch.json`: its `inputs` table maps each read-only upstream input to its location; below, `<key>` denotes that input's location, so you read `<key>/<subpath>`. `brainstorm` is a PIPELINE_INPUT, so `<brainstorm>` resolves to the module root.

| Path | Schema / Format | Use |
|---|---|---|
| `<brainstorm>/brainstorm.md` | Custom markdown; frontmatter `Status: approved` | The frozen module-root input (approval already gate-verified). Read only inside sub-Tasks — the Wave-1 decomposer and the Wave-3 reviewers; the main thread never loads its body and no script reads it. |

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + `framework/references/schemas/envelope.schema.json` | This stage's status contract. |
| `design.md` | Custom markdown (section template in `references/design-template.md`) | Design document (overview §1.1–1.6 + §1.7 submodule index). §1.6 carries a pointer to `clocks.json`, not a clock table. |
| `manifest.json` | Custom JSON (child registry) | Child-partition SSoT (`module`, `children[]` with `name` / `doc` / `rtl_modules[]` / `brainstorm_anchor`); consumed by simulation-plan / rtl-design. |
| `<child>.md × N` | Custom markdown (template in `references/child-design-template.md`) | Per-child sub-design (frontmatter + §1–§5); consumed by rtl-design (§2/§3). |
| `check-hints/<child>.json × N` | `references/check-hints.schema.json` | Per-child verification check hints, authored by that child's Wave-2 sub-Task (one file each: children run in parallel); consumed by simulation-plan. |
| `ppa.json` | `references/ppa.schema.json` | PPA-targets SSoT, authored by Wave 1 from brainstorm D6 (`[]` when none); declared input of synthesis / power-analysis. |
| `clocks.json` | `references/clocks.schema.json` | Clock-definitions SSoT (name / period / relationship / generated), authored by Wave 1; sole source of `constraints/<TOP>.{sdc,sgdc}` and declared input of simulation-plan / rtl-design. |
| `features.json` | `references/features.schema.json` | Feature-list SSoT, authored by Wave 1; every `id` must be referenced by ≥1 `check-hints/<child>.json` `source_feature`, and simulation-plan derives testpoints and tests from it. |
| `top-io.json` | `references/top-io.schema.json` | Top-level IO SSoT, authored by Wave 1; sole source of `constraints/<TOP>.{sdc,sgdc}` IO delays and of the TB agent signal lists. |
| `interconnects.json` | `references/interconnects.schema.json` | Cut-edge SSoT, authored by Wave 1; `derive-ports` attributes each wire to the children that touch it. |
| `constraints/<TOP>.sgdc` | SpyGlass SGDC | Lint/CDC constraint source of truth (generated by `derive-constraints`). |
| `constraints/<TOP>.sdc` | SDC | Synthesis/STA constraint source of truth (generated by `derive-constraints`). |
| `spec-review/<child>.md × N` + `decisions.md` | Custom markdown | Per-child semantic review, written by that child's Wave-3 reviewer (one file each: reviewers run in parallel); `decisions.md` records the user's per-finding resolution at the Step-7 gate. The stage's proposed oracle. |

## Workflow

You are loaded on the main thread as a thin Level-0 dispatcher. You hold no document body — `brainstorm.md`, `design.md`, and every `<child>.md` are read/written only inside sub-Task contexts.

### Fan-out Dispatch Contract

- **No Level 2 dispatch:** dispatch only Level-1 sub-Tasks; none dispatches a sub-Task of its own.
- **Dispatch-and-wait:** after dispatching, send a brief status and end the turn. Reap each, and finalize only after all dispatched sub-Tasks have reported, never against a partial set.
- **Sub-Task `STATUS: BLOCKED`:** if a dispatched sub-Task comes back blocked (no usable result: a crash, not a `fail` verdict), finalize this stage `status=fail` + `fail_reason` listing the failed children (via the finalize early-fail entry) and defer per-child re-dispatch to a repair round.

### Step 1: Entry — determine scope, pick the entry point

Your previous round, if any, is already present in `{workdir}`; edit it in place. Read `{workdir}/dispatch.json` first: its `scope` narrows what this round may touch, its `caused_by` names the failing envelopes to read, and its `reasons` carries a human's judgment on the repair. Then branch on whether a `<child>.md` is already in `{workdir}`:

- **A `<child>.md` is present:** a repair round. A `<child>.md` is Wave-2 output, written only *after* the Step-3 partition gate, so its presence proves the partition was gate-confirmed in a prior round. Scope is the union of `dispatch.json`'s `scope` and what the `caused_by` envelopes attribute; Read each envelope once. Dispatch one design.md-level rework sub-Task, then **re-enter the main chain at Step 5** and flow through Steps 6–8, ending at Step 8. Steps 2–4 (the partition) are skipped, since `manifest.json` is immutable after the partition gate; Step 6 (the semantic gate) re-runs on this pass, so the promoted gate is always fresh.
- **No `<child>.md` in `{workdir}`:** no partition has been gate-confirmed yet (a first delivery, or a run interrupted or reset before that gate). Re-derive in full from Step 2 (a fresh partition, including the human partition gate), ending at Step 8. `design.md` or `manifest.json` alone do not qualify: they are Wave-1 output, written *before* the gate.

**Early-fail exit.** Whenever a documented failure below cannot be resolved, close the run with the finalize early-fail entry, not a hand-assembled envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py finalize \
  --workdir {workdir} --module {module} --status fail --fail-reason "<one-line reason>"
```

### Main chain at a glance

| Step | Executor | Does → produces | On failure |
|---|---|---|---|
| 2 | Wave 1 (sub-Task) | decompose → `manifest.json` + `design.md` §1.1–1.7 + `ppa.json` | `STATUS: BLOCKED` → Fan-out Contract |
| 3 | script + human | `derive-ports` (per-child inter-module wires) → partition gate | rework / early-fail; merge → Step 2 |
| 4 | Wave 2 (sub-Task ×N) | one `<child>.md` per child | `STATUS: BLOCKED` → Fan-out Contract |
| 5 | script | coverage gate + constraint derivation | → rework / early-fail |
| 6 | Wave 3 (reviewers ×N) + script | semantic review → gate verdict | `trip` → Step 7 |
| 7 | human | `design.md` gate | reject → Step 5 |
| 8 | script | `finalize` → `result.json` | non-zero → BLOCKED |

### Step 2: Wave 1 — decompose

Dispatch one Level-1 sub-Task per `references/decompose-task-contract.md`. In its own context it reads `<brainstorm>/brainstorm.md` and writes `manifest.json`, the `design.md` §1.1–1.7 (overview + §1.7 submodule index), and `ppa.json`; the partition strategy, field schemas, and `STATUS` return protocol live in that contract (do not restate them here).

After dispatching, end the turn, then reap and proceed to Step 3 only after it reports.

### Step 3: Partition gate (script + human)

Run `derive-ports` to compute each child's inter-module ports (the `interconnects.json` wires whose producers/consumers include one of that child's `rtl_modules`) — its output is both what the human reviews here and what Step 4 injects into each child sub-Task:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py derive-ports --workdir {workdir}
```

On a non-zero exit, stderr names the defect. Do NOT gate: route a Wave-1 rework sub-Task to fix it, or close via early-fail if it is unresolvable.

Then present an N-child summary from manifest metadata only: `Grep manifest.children[].{name,role}` plus the `derive-ports` JSON (inter-module wires per child). **Do NOT read `design.md` §1.4.x into the main thread** — a body on the main thread invites a main-thread Edit, which is how wave-authored content gets amended outside its wave. Point the user to §1.4 to inspect it themselves.

The human then either:
- **confirms** the partition, or
- gives **merge feedback**, then you re-dispatch Wave 1 with the new grouping and re-run `derive-ports`.

Guardrails: **never auto-split**. If a cluster's `rtl_modules` count looks unusually large, flag it for the human to re-check for a missed clean-handshake cut point, never a size-based split.

### Step 4: Wave 2 — child sub-designs (×N)

Dispatch N sub-Tasks (one per child), each writing `{workdir}/<child>.md` per `references/child-design-template.md`. Each child's `frontmatter.ports` is the derived inter-module wire list (Step 3) plus any child-authored top-IO ports. **Wave 2 is ALWAYS dispatched (even N=1 is one sub-Task).**

After dispatching all N, end the turn; reap each child and proceed only after all N have reported.

### Step 5: Coverage gate + constraint derivation (script)

Run `check-coverage` to gate the design.md and children before the review:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py check-coverage --workdir {workdir}
```

It prints the verdict to stdout (sub-blocks: `frontmatter_subset` / `structure`); exit 0 = pass. On a non-zero exit, **fix nothing yourself**; you only route to a rework sub-Task:
- **coverage violations** (a verdict is on stdout): route by category (below), then re-run, looping until clean.
- **a table could not be parsed** (it raised; stderr names the defect): route a Wave-1 rework, or early-fail if unresolvable.

| Violation category | Rework target |
|---|---|
| `features_schema_violations`; `clock_domain_violations`; `purity_violations`; `top_io_schema_violations`; `interconnects_schema_violations`; `width_violations`; `interconnect_violations` | Wave-1 rework (re-partition the manifest; the authored sidecars; `design.md` narrative) |
| `frontmatter_subset`; `hint_column_violations`; `feature_coverage_gaps`; `top_io_driver_violations` | the affected Wave-2 child rework |

**On a clean coverage gate, immediately run `derive-constraints`:**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py derive-constraints --workdir {workdir}
```

It generates `constraints/<TOP>.{sdc,sgdc}` from `clocks.json` + `top-io.json`. Running it here, before the design.md gate, surfaces defects the coverage gate cannot see (clocks.json schema violations, the exactly-one-`primary` rule, reset polarity/kind, clock-name collisions), so a rework is still cheap. On a non-zero exit, stderr names the exact defect: route a Wave-1 rework sub-Task and re-run this step, or close via early-fail if unresolvable.

### Step 6: Wave 3 — semantic review

On **every** pass through the main chain, dispatch **N per-child Level-1 reviewers** (one per `manifest.children[]`) per `references/spec-review-task-contract.md`, paths only. Each writes its own `{workdir}/spec-review/<child>.md`; you read no body and re-type nothing. What a finding must state lives in that contract — do not restate or reinterpret it here.

Reap all N.

### Step 7: design.md gate (human)

Path-handoff — present these to the user, echoing no body:

- the `design.md` (+ per-child) paths and the coverage verdict;
- one `spec-review/<child>.md` path per child;
- the `ppa.json` content **verbatim**: the numeric acceptance targets synthesis/power-analysis gate on, transcribed by Wave 1 with no other human-visible surface, and the approval covers them.

The user reads the reviewers' own words. You do not summarize the findings, rank them, or decide which ones matter — a review relayed through your summary is your judgment wearing the reviewer's name.

If the user accepts a finding a reviewer called blocking, write their reason — **their words, not yours** — to `{workdir}/spec-review/decisions.md`. It is promoted with the review files, so what the user endorsed over a reviewer's objection, and why, is what `signoff` later pins.

One structural case a rework cannot clear: a defect rooted in the child partition, since `manifest.json` is read-only after the Step-3 gate. Close via early-fail (`requirements need revision`) for a fresh run.

On reject: route a rework sub-Task, body off the main thread, then **re-enter the main chain at Step 5** and flow through 5→6→7 again. The rework's reviewers write fresh files, so a stale clean review cannot survive a body edit.

### Step 8: Finalize (script, mandatory)

Run finalize to write the stage's `result.json`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py finalize \
  --workdir {workdir} --module {module} --status <pass|fail>
```

You supply only the human-gate outcome: `--status` (approve/reject). finalize re-runs `check-coverage` and `derive-constraints` in-process (both were clean at Step 5, so a failure now means an artifact was edited after the gate — BLOCKED, not a routable fail) and validates the Wave-1-authored `{workdir}/ppa.json` sidecar (a missing or invalid one is BLOCKED, not a silent default; override with `--ppa-targets` only if needed). Exit 0 = `result.json` written (status pass or fail); a non-zero exit is a program exception (BLOCKED, reason on stderr), not a `status=fail`.

## Completion Gate

- **Mechanical gate:** `spec check-coverage` exit 0 AND `spec derive-constraints` exit 0 (Step 5, both pre-human-gate; the latter re-run by finalize as the divergence-proof invariant).
- **Semantic gate:** every child has a `spec-review/<child>.md`, and every blocking finding in them was either fixed or accepted by the user with their reason in `decisions.md`. Both are in `artifacts[]`.
- **Human gate:** the design.md gate is approved (incl. port roles, reset polarity, clock relationships, the presented `ppa.json`): the engineering-soundness judgment the mechanical and semantic gates cannot catch.
- **Finalize:** `spec finalize` wrote `result.json` (Step 8), owning status / `top_module` / `fail_reason` / `artifacts[]`; its verdict is schema-validated externally, not by you.
- No Iron Rule or Red Flag was triggered.

## Return Contract

**Do not decide what happens after you complete**; control returns to the caller, which decides from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is incomplete (no cross-session "already complete" flag), so a repair round or a compaction resume just re-enters the main chain at Step 5 and re-runs it idempotently.

## Bundled References

- [`references/design-template.md`](references/design-template.md) — design.md section template.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/ppa.schema.json`](references/ppa.schema.json) — the `ppa.json` PPA-targets sidecar schema (the cross-stage PPA dim namespace).
- [`references/decompose-task-contract.md`](references/decompose-task-contract.md) — Wave-1 decompose sub-Task contract (Step 2).
- [`references/spec-review-task-contract.md`](references/spec-review-task-contract.md) — per-child reviewer sub-Task contract (Step 6).
