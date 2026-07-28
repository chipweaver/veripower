---
name: specification
description: Use when writing or reviewing design specification (design.md), defining interfaces or constraints (SDC/SGDC), or updating from rework feedback; not for RTL implementation or verification.
---

# Requirements and Specification Freeze

Your sole responsibility: derive a frozen design source of truth from an approved `<brainstorm>/brainstorm.md` — `design.md` (overview §1.1–1.6 + §1.7 submodule index) + per-child `<child>.md` + `manifest.json` + `ppa.json` + `clocks.json` + `features.json` + `timing-scenarios.json` + `top-io.json` + `interconnects.json` + `check-hints/<child>.json` + a pair of constraint files (`<TOP>.sdc` / `<TOP>.sgdc`). You are a thin Level-0 dispatcher: three sub-agent waves, two path-handoff gates, deterministic main-thread scripts in between; the brainstorm dialogue lives in the pre-pipeline `brainstorm` skill.

## Iron Rule

Your boundary:

- **Write only under `{workdir}`** (artifacts + `result.json`); never touch another module's artifacts. Reading templates and upstream inputs outside is fine.
- **No brainstorm here.** Consume the frozen, approved `brainstorm.md`; run the two path-handoff gates, but hold no document body and drive no D0–D7 dialogue.
- **No LLM constraint overlay.** `derive-constraints` generates and self-checks the constraint files; you neither hand-write nor re-check them.
- **`design.md` carries no by-reference jumps** (`see brainstorm`, `see spec D`, …): it is the unique source of truth, so inline every referenced passage verbatim.
- **Reference PPA targets by pointing at `ppa.json`, never by restating the numbers**: this is the one sanctioned by-reference pointer (brainstorm content is still inlined verbatim).
- **`manifest.json` is read-only after the partition gate**; changing N takes a fresh run.
- **Minimal change on re-dispatch**: with a prior `design.md` on disk, touch only what the round requires and leave every other file byte-identical.
- **Scripts are black boxes**: never Read their source (only to debug a suspected script bug); invoke them per the documented commands and act on their documented failure output.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{failing_result}` | Optional. The failed stage's canonical `result.json` path (`stage_specific` shape per that stage's schema); when present, supplies this round's repair scope (Step 1). |
| `{directive_path}` | Optional. Fix-scope hint file (Orchestrator reasoning, or forwarded triage `result.json`); when present, Read it first. |

### External reference inputs

Each read-only upstream input's location is injected — read `inputs.json` in your `{workdir}`; below, `<key>` denotes that input's location, so you read `<key>/<subpath>`. `brainstorm` is a PIPELINE_INPUT, so `<brainstorm>` resolves to the module root.

| Path | Schema / Format | Use |
|---|---|---|
| `<brainstorm>/brainstorm.md` | Custom markdown; frontmatter `Status: approved` | The frozen module-root input (approval already gate-verified). Read only inside sub-Tasks and passed by path to `check-coverage --brainstorm`; the main thread never loads its body. |

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + `framework/references/schemas/envelope.schema.json` | This stage's status contract. |
| `design.md` | Custom markdown (section template in `references/design-template.md`) | Design document (overview §1.1–1.6 + §1.7 submodule index). §1.6 carries a pointer to `clocks.json`, not a clock table. |
| `manifest.json` | Custom JSON (child registry) | Child-partition SSoT (`module`, `children[]` with `name` / `doc` / `rtl_modules[]` / `brainstorm_anchor` / `role`); consumed by simulation-plan / rtl-design. |
| `<child>.md × N` | Custom markdown (template in `references/child-design-template.md`) | Per-child sub-design (frontmatter + §1–§5); consumed by rtl-design (§2/§3). |
| `check-hints/<child>.json × N` | `references/check-hints.schema.json` | Per-child verification check hints, authored by that child's Wave-2 sub-Task (one file each: children run in parallel); consumed by simulation-plan. |
| `ppa.json` | `references/ppa.schema.json` | PPA-targets SSoT, authored by Wave 1 from brainstorm D6 (`[]` when none); declared input of synthesis / power-analysis. |
| `clocks.json` | `references/clocks.schema.json` | Clock-definitions SSoT (name / freq / period / relationship / generated), authored by Wave 1; sole source of `constraints/<TOP>.{sdc,sgdc}` and declared input of simulation-plan / rtl-design. |
| `features.json` | `references/features.schema.json` | Feature-list SSoT, authored by Wave 1; every `id` must be referenced by ≥1 `check-hints/<child>.json` `source_feature`, and simulation-plan derives testpoints and tests from it. |
| `timing-scenarios.json` | `references/timing-scenarios.schema.json` | Interface-timing-scenario SSoT, authored by Wave 1; simulation-plan authors one sequence per `id`. §1.5 keeps the waveforms. |
| `top-io.json` | `references/top-io.schema.json` | Top-level IO SSoT, authored by Wave 1; sole source of `constraints/<TOP>.{sdc,sgdc}` IO delays and of the TB agent signal lists. |
| `interconnects.json` | `references/interconnects.schema.json` | Cut-edge SSoT, authored by Wave 1; `derive-ports` attributes each wire to the children that touch it. |
| `constraints/<TOP>.sgdc` | SpyGlass SGDC (template in `references/sgdc-template.md`) | Lint/CDC constraint source of truth (generated by `derive-constraints`). |
| `constraints/<TOP>.sdc` | SDC (template in `references/sdc-template.md`) | Synthesis/STA constraint source of truth (generated by `derive-constraints`). |
| `spec-review.json` | `references/spec-review.schema.json` | Gating per-child semantic review (Wave 3; faithfulness + conformance block, soundness must-acknowledge). |

## Workflow

You are loaded on the main thread as a thin Level-0 dispatcher. You hold no document body — `brainstorm.md`, `design.md`, and every `<child>.md` are read/written only inside sub-Task contexts.

### Fan-out Dispatch Contract

- **No Level 2 dispatch:** dispatch only Level-1 sub-Tasks; none dispatches a sub-Task of its own.
- **Dispatch-and-wait:** after dispatching, send a brief status and end the turn. Reap each, and finalize only after all dispatched sub-Tasks have reported, never against a partial set.
- **Sub-Task `STATUS: BLOCKED`:** if a dispatched sub-Task comes back blocked (no usable result: a crash, not a `fail` verdict), finalize this stage `status=fail` + `fail_reason` listing the failed children (via the finalize early-fail entry) and defer per-child re-dispatch to a repair round.

### Step 1: Entry — determine scope, pick the entry point

Your previous round, if any, is already present in `{workdir}`; edit it in place. When `{directive_path}` is injected, Read it first: its `fix_locus` narrows the scope. Then branch on whether a `<child>.md` is already in `{workdir}`:

- **A `<child>.md` is present:** a repair round. A `<child>.md` is Wave-2 output, written only *after* the Step-4 partition gate, so its presence proves the partition was gate-confirmed in a prior round. Scope is `{directive_path}`'s `fix_locus` when injected, otherwise the `{failing_result}`'s `stage_specific` attribution; Read that trigger once, and early-fail (`failing_result not readable: <path>`) if it cannot be read. Dispatch one design.md-level rework sub-Task, then **re-enter the main chain at Step 6** and flow through Steps 7–9, ending at Step 9. Steps 2–5 (the partition) are skipped, since `manifest.json` is immutable after the partition gate; Step 7 (the semantic gate) re-runs on this pass, so the promoted gate is always fresh.
- **No `<child>.md` in `{workdir}`:** no partition has been gate-confirmed yet (a first delivery, or a run interrupted or reset before that gate). Re-derive in full from Step 2 (a fresh partition, including the human partition gate), ending at Step 9. `design.md` or `manifest.json` alone do not qualify: they are Wave-1 output, written *before* the gate.

**Early-fail exit.** Whenever a documented failure below cannot be resolved, close the run with the finalize early-fail entry, not a hand-assembled envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py finalize \
  --workdir {workdir} --module {module} --status fail --fail-reason "<one-line reason>"
```

### Main chain at a glance

| Step | Executor | Does → produces | On failure |
|---|---|---|---|
| 2 | Wave 1 (sub-Task) | decompose → `manifest.json` + `design.md` §1.1–1.7 + `ppa.json` | `STATUS: BLOCKED` → Fan-out Contract |
| 3 | script | `derive-ports` (per-child inter-module wires) | → Wave-1 rework / early-fail |
| 4 | human | partition gate | merge → Step 2 |
| 5 | Wave 2 (sub-Task ×N) | one `<child>.md` per child | `STATUS: BLOCKED` → Fan-out Contract |
| 6 | script | coverage gate + constraint derivation | → rework / early-fail |
| 7 | Wave 3 (reviewers ×N) + script | semantic review → gate verdict | `trip` → Step 8 |
| 8 | human | `design.md` gate | reject → Step 6 |
| 9 | script | `finalize` → `result.json` | non-zero → BLOCKED |

### Step 2: Wave 1 — decompose

Dispatch one Level-1 sub-Task per `references/decompose-task-contract.md`. In its own context it reads `<brainstorm>/brainstorm.md` and writes `manifest.json`, the `design.md` §1.1–1.7 (overview + §1.7 submodule index), and `ppa.json`; the partition strategy, field schemas, and `STATUS` return protocol live in that contract (do not restate them here).

After dispatching, end the turn, then reap and proceed to Step 3 only after it reports.

### Step 3: Derive inter-module ports

Run `derive-ports` to compute each child's inter-module ports (the `interconnects.json` wires whose producers/consumers include one of that child's `rtl_modules`):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py derive-ports --workdir {workdir}
```

On a non-zero exit, stderr names the defect. Do NOT gate: route a Wave-1 rework sub-Task to fix it, or close via early-fail if it is unresolvable.

### Step 4: Partition gate (human)

Present an N-child summary from manifest metadata only: `Grep manifest.children[].{name,role}` plus the `derive-ports` JSON (inter-module wires per child). **Do NOT read `design.md` §1.4.x into the main thread**; point the user to §1.4 to inspect it themselves.

The human then either:
- **confirms** the partition, or
- gives **merge feedback**, then you re-dispatch Wave 1 with the new grouping and re-run `derive-ports`.

Guardrails: **never auto-split**. If a cluster's `rtl_modules` count looks unusually large, flag it for the human to re-check for a missed clean-handshake cut point, never a size-based split.

### Step 5: Wave 2 — child sub-designs (×N)

Dispatch N sub-Tasks (one per child), each writing `{workdir}/<child>.md` per `references/child-design-template.md`. Each child's `frontmatter.ports` is the derived inter-module wire list (Step 3) plus any child-authored top-IO ports. **Wave 2 is ALWAYS dispatched (even N=1 is one sub-Task).**

After dispatching all N, end the turn; reap each child and proceed only after all N have reported.

### Step 6: Coverage gate + constraint derivation (script)

Run `check-coverage` to gate the design.md and children before the review:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py check-coverage --workdir {workdir} --brainstorm <brainstorm>/brainstorm.md
```

It prints the coverage verdict to stdout (sub-blocks: `brainstorm_coverage` / `frontmatter_subset` / `token_survival` / `self_containment` / `structure`); exit 0 = pass. On a non-zero exit, **fix nothing yourself**; you only route to a rework sub-Task:
- **coverage violations** (a verdict is on stdout): route by category (below), then re-run, looping until clean.
- **a table could not be parsed** (it raised; stderr names the defect): route a Wave-1 rework, or early-fail if unresolvable.

| Violation category | Rework target |
|---|---|
| `gaps` / `orphans`; `features_schema_violations`; `timing_scenarios_schema_violations`; period; Clock-Domain; `purity_violations`; `top_io_schema_violations`; `interconnects_schema_violations`; `width_violations`; `interconnect_violations`; `top_io_driver_violations` | Wave-1 rework (re-partition the manifest; the authored sidecars; `design.md` narrative) |
| `token_survival`; `frontmatter_subset`; `self_containment`; `hint_column_violations`; feature coverage | the affected Wave-2 child rework |

**On a clean coverage gate, immediately run `derive-constraints`:**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py derive-constraints --workdir {workdir}
```

It generates `constraints/<TOP>.{sdc,sgdc}` from `clocks.json` + `top-io.json`. Running it here, before the design.md gate, surfaces defects the coverage gate cannot see (clocks.json schema violations, the exactly-one-`primary` rule, reset polarity/kind, clock-name collisions), so a rework is still cheap. On a non-zero exit, stderr names the exact defect: route a Wave-1 rework sub-Task and re-run this step, or close via early-fail if unresolvable.

### Step 7: Wave 3 — semantic review (gating)

On **every** pass through the main chain, dispatch **N per-child Level-1 reviewers** (one per `manifest.children[]`) per `references/spec-review-task-contract.md`, paths only: you read no body. The lens definitions, the gating split, and scope boundaries live in that contract; do not restate or reinterpret them here.

> **Gate semantics (block-in-place).** A `gate=trip` is not an automatic fail-out: it does **NOT** itself route rework or write `status=fail`. It blocks `status=pass` **in place** and surfaces the findings to the Step-8 design.md gate, where a human resolves each one (reject-and-rework, waive, or early-fail).

Aggregate the reaped reports into `{workdir}/spec-review.json` (schema `references/spec-review.schema.json`):
- On `STATUS: DONE` + valid JSON, fold the reviewer's findings in, stamping each with its `child`.
- On `STATUS: BLOCKED` or unparseable JSON, record one `unavailable`-lens finding for that child (`severity: minor`), so a crashed reviewer can't read as a silent clean pass.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py validate-review --review {workdir}/spec-review.json
```

On a non-zero exit, the JSON you assembled is invalid: stderr names the schema violation. Re-assemble and re-run (a main-thread fix, NOT a re-dispatch).

On exit 0 it prints the gate verdict `{"gate":"trip"|"clear","flagged":[{child,lens,severity}…],"must_ack":[{child,severity}…]}`: the mechanical `lens × severity` reduction, computed by the script, not by eye. You copy nothing into any envelope; finalize re-derives it from the promoted `spec-review.json`.

On `clear` you proceed to the Step-8 gate; on `trip` the findings are resolved there (block-in-place, above). `must_ack` advisories and any `unavailable` markers ride to that gate for acknowledgement. This stage never auto-fixes design.md.

### Step 8: design.md gate (human)

Path-handoff — present these to the user, echoing no body:
- the `design.md` (+ per-child) paths and the coverage verdict;
- the `spec-review.json` verdict: `spec_gate.flagged` blocking + `spec_gate.must_ack` advisory + any `review unavailable` ack item (summaries in `spec-review.json`);
- the `ppa.json` content **verbatim**: the numeric acceptance targets synthesis/power-analysis gate on, transcribed by Wave 1 with no other human-visible surface, and the approval covers them.

Surface a `must_ack` or `review unavailable` item only if NEW or CHANGED vs the prior promoted `spec-review.json` wave (match by `child`+`summary`); an unchanged one was already acknowledged (anti rubber-stamp). A `review unavailable` item means the gate did not run for that child, so the approval explicitly acknowledges it, never a silent clean pass.

If `spec_gate.gate==trip`, resolve each `flagged` item in exactly one of three ways. **This is the single home of the waiver protocol:**
- **fixed**: reject and rework it (below).
- **waived (human waiver)**: record a waiver (schema `spec_gate.waived`) whose **`reason` is human-authored: PROMPT the operator and block until provided, never auto-write it**. A waiver keys on **(child, lens)**: one waiver clears every flagged finding of that pair. For a **critical-severity faithfulness** waiver, surface: "no downstream stage re-checks spec-vs-brainstorm, so this is a terminal accept." Waivers reach the envelope only via finalize `--waived`.
- **partition-rooted**: the defect is rooted in the child partition, not a design.md body (`manifest.json` is read-only after the partition gate), so a design.md-only rework cannot clear it; close via early-fail (`requirements need revision`) for a fresh run.

**Approve precondition (finalize re-checks it in-process):** you MUST NOT accept the user's approval unless `spec_gate.gate==clear` OR every `flagged` finding is waived per the waiver protocol above; if not, resolve first.

On reject: route a rework sub-Task, body off the main thread. The rework first clears `spec_gate=clear` (invalidate-on-rework, so a post-clear body edit cannot leave a stale `clear`), then **re-enter the main chain at Step 6** and flow through 6→7→8 again.

### Step 9: Finalize (script, mandatory)

Run finalize to write the stage's `result.json`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py finalize \
  --workdir {workdir} --module {module} --status <pass|fail> \
  --waived '<spec_gate.waived[] JSON>'
```

You supply only the human-gate outcome: `--status` (approve/reject) and `--waived` (`[]` if none). finalize validates the Wave-1-authored `{workdir}/ppa.json` sidecar (a missing or invalid one is BLOCKED, not a silent default; override with `--ppa-targets` only if needed) and **downgrades a `--status pass` to a written `status=fail`** if the Step-8 approve precondition is unmet (`spec_gate` neither clear nor fully waived). Exit 0 = `result.json` written (status pass or fail); a non-zero exit is a program exception (BLOCKED, reason on stderr), not a `status=fail`.

## Red Flags

| Excuse | Reality |
|---|---|
| "The design looks complete — I'll mark it pass" without the user's approval at the design.md gate | The design.md gate is architectural, not a formality. Marking pass without it ships an unapproved spec downstream. |
| "Minimum fields look mostly there — pass" | Mark pass only when the required (gated) columns are complete (see the design-template completeness gate table). Partial ≠ pass. |
| "I'll just Edit this wave-output design.md/`<child>.md` body to fix a number" | The main thread holds no body; numerics are locked in the frozen brainstorm. Amend a body only by re-dispatching its wave sub-Task — never by main-thread Edit. |

## Completion Gate

- **Mechanical gate:** `spec check-coverage` exit 0 AND `spec derive-constraints` exit 0 (Step 6, both pre-human-gate; the latter re-run by finalize as the divergence-proof invariant).
- **Semantic gate:** the Step-7 `spec_gate` verdict cleared per the Step-8 approve precondition; `stage_specific.spec_gate` written; `spec-review.json` in `artifacts[]`.
- **Human gate:** the design.md gate is approved (incl. port roles, reset polarity, clock relationships, the presented `ppa.json`): the engineering-soundness judgment the mechanical and semantic gates cannot catch.
- **Finalize:** `spec finalize` wrote `result.json` (Step 9), owning status / `top_module` / `spec_gate` / `fail_reason` / `artifacts[]`; its verdict is schema-validated externally, not by you.
- No Iron Rule or Red Flag was triggered.

## Return Contract

**Do not decide what happens after you complete**; control returns to the caller, which decides from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is incomplete (no cross-session "already complete" flag), so a repair round or a compaction resume just re-enters the main chain at Step 6 and re-runs it idempotently.

## Bundled References

- [`references/design-template.md`](references/design-template.md) — design.md section template + minimum field completeness gate table.
- [`references/sdc-template.md`](references/sdc-template.md) — SDC generated-output reference (what `derive-constraints` emits).
- [`references/sgdc-template.md`](references/sgdc-template.md) — SGDC generated-output reference (what `derive-constraints` emits).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema (`schema_version: 1`).
- [`references/ppa.schema.json`](references/ppa.schema.json) — the `ppa.json` PPA-targets sidecar schema (the cross-stage PPA dim namespace).
- [`references/spec-review.schema.json`](references/spec-review.schema.json) — gating semantic-review schema (Wave 3, Step 7).
- [`references/decompose-task-contract.md`](references/decompose-task-contract.md) — Wave-1 decompose sub-Task contract (Step 2).
- [`references/spec-review-task-contract.md`](references/spec-review-task-contract.md) — per-child reviewer sub-Task contract (Step 7).
