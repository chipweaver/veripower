---
name: specification
description: Use when writing or reviewing design specification (design.md), defining interfaces or constraints (SDC/SGDC), or updating from rework feedback; not for RTL implementation or verification.
---

# Requirements and Specification Freeze

Your sole responsibility: derive a frozen design source of truth from an approved `<brainstorm>/brainstorm.md` — `design.md` (overview §1.1–1.6 + submodule §1.7+) + per-child `<child>.md` + `manifest.json` + `ppa.json` + a pair of constraint files (`<TOP>.sdc` / `<TOP>.sgdc`). You are a thin Level-0 dispatcher: three sub-agent waves, two path-handoff gates, deterministic main-thread scripts in between; the brainstorm dialogue lives in the pre-pipeline `brainstorm` skill.

## When to Use

- First-time design.md derivation from an approved brainstorm.md.
- Specification modification on an existing module (a repair round amends design.md only — brainstorm.md is frozen and read-only).
- Reviewing or modifying an existing design.md.
- Creating or updating SDC/SGDC constraint files.

## Iron Rule

Your boundary:

- **Write only under `{workdir}`** (artifacts + `result.json`); never read or write other modules' artifacts. Reading reference material outside `{workdir}` (plugin-internal templates, upstream canonical inputs) is allowed.
- **No brainstorm here.** Consume a frozen `<brainstorm>/brainstorm.md` (produced by the pre-pipeline `brainstorm` skill; `design-flow`'s entry gate already verified `Status: approved` — a missing/draft brainstorm means the user must run `Skill(veripower:brainstorm)` first). Run the two path-handoff gates but hold no document body and drive no D0–D7 dialogue.
- **Constraint correctness** (periods consistent, IO delays / `abstract_port`s present) is generated and self-checked by `derive-constraints` — there is no LLM constraint overlay and no separate constraint checker.
- **`design.md` must not contain by-reference jumps.** `design.md` is the unique source of truth; downstream stages do not read `brainstorm.md`. Any `see brainstorm`, `see spec D`, etc. = information loss; the referenced passage must be inlined verbatim.
- **`design.md` and every `<child>.md` MUST reference the PPA targets by pointing at `ppa.json`, never restate the numeric target values in prose** (carrier line in `design-template.md` §1.1). `ppa.json` is the single home of PPA numbers — synthesis and power-analysis bind to it directly as their acceptance standard, so a restated number can silently drift from the value they actually gate on. This is the one sanctioned by-reference pointer; brainstorm content still must be inlined verbatim.
- **`manifest.json` is read-only after the partition gate.** Changes to N require a fresh specification run (or re-dispatching Wave 1 with new grouping before the partition gate is reconfirmed).
- **Minimal edit on any re-dispatch with a prior valid `design.md` on disk.** Edit only what this round's task requires: `{directive_path}`'s `fix_locus`, when injected, is authoritative for scope; otherwise a repair round amends `design.md` only. Every file outside that scope — `manifest.json`, the `<child>.md` set, `ppa.json`, the constraint files — MUST stay byte-identical to the prior run.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

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

When `{failing_result}` is provided, read it once at its path as reference; a first delivery depends only on existing artifacts under `{workdir}`.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + `framework/references/schemas/envelope.schema.json` | This stage's status contract. |
| `design.md` | Custom markdown (section template in `references/design-template.md`) | Design document (overview §1.1–1.6 + submodule §1.7+). |
| `manifest.json` | Custom JSON (child registry) | Child-partition SSoT (`module`, `children[]` with `name` / `doc` / `rtl_modules[]` / `brainstorm_anchor` / `role`); consumed by simulation-plan / rtl-design. |
| `<child>.md × N` | Custom markdown (template in `references/child-design-template.md`) | Per-child sub-design (frontmatter + §1–§5); consumed by rtl-design (§2/§3), simulation-plan (§5). |
| `ppa.json` | JSON array `[{dim, target}, …]` | PPA-targets SSoT, authored by Wave 1 from brainstorm D6 (`[]` when none); declared input of synthesis / power-analysis. |
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
| 2 | Wave 1 (sub-Task) | decompose → `manifest.json` + `design.md` overview + `ppa.json` | `STATUS: BLOCKED` → Fan-out Contract |
| 3 | script | `derive-ports` (per-child inter-module wires) | → Wave-1 rework / early-fail |
| 4 | human | partition gate | merge → Step 2 |
| 5 | Wave 2 (sub-Task ×N) | one `<child>.md` per child | `STATUS: BLOCKED` → Fan-out Contract |
| 6 | script | coverage gate + constraint derivation | → rework / early-fail |
| 7 | Wave 3 (reviewers ×N) + script | semantic review → gate verdict | `trip` → Step 8 |
| 8 | human | `design.md` gate | reject → Step 6 |
| 9 | script | `finalize` → `result.json` | non-zero → BLOCKED |

### Step 2: Wave 1 — decompose

Dispatch one Level-1 sub-Task per `references/decompose-task-contract.md`. In its own context it reads `<brainstorm>/brainstorm.md` and writes `manifest.json`, the `design.md` overview (§1.1–1.7), and `ppa.json`; the partition strategy, field schemas, and `STATUS` return protocol live in that contract (do not restate them here).

After dispatching, end the turn, then reap and proceed to Step 3 only after it reports.

### Step 3: Derive inter-module ports

Run `derive-ports` to compute each child's inter-module ports (the §1.4.2 wires whose Producer/Consumer RTL module is in that child's `rtl_modules`):

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
| `gaps` / `orphans`; `structure` §1.3/§1.5 columns; period (R-B); Clock-Domain (R-F); `purity_violations`; `interconnect_violations` (§1.4.2 Width / Clock Domain); `top_io_driver_violations` (§1.4.1 output Owner) | Wave-1 rework (re-partition the manifest; `design.md` overview tables) |
| `token_survival`; `frontmatter_subset`; `self_containment`; child §5 columns; feature coverage (R-C) | the affected Wave-2 child rework |

**On a clean coverage gate, immediately run `derive-constraints`:**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py derive-constraints --workdir {workdir}
```

It generates `constraints/<TOP>.{sdc,sgdc}` from the §1.6 and §1.4.1 tables, self-checked before writing. Running it here, before the design.md gate, surfaces table defects the coverage gate cannot see (enum values, reset polarity/kind, clock-name collisions), so a rework is still cheap. On a non-zero exit, stderr names the exact defect: route a Wave-1 rework sub-Task and re-run this step, or close via early-fail if unresolvable.

### Step 7: Wave 3 — semantic review (gating)

Run this wave after Step 6 is fully clean and before the design.md gate, on **every** pass through the main chain. Dispatch **N per-child Level-1 reviewers** (one per `manifest.children[]`) per `references/spec-review-task-contract.md`, paths only: you read no body. The lens definitions, the gating split, and scope boundaries live in that contract; do not restate or reinterpret them here.

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

Path-handoff: give the user the `design.md` (+ per-child) paths, the coverage verdict, and the `spec-review.json` verdict (`spec_gate.flagged` blocking items + `spec_gate.must_ack` advisory items + any `review unavailable` ack item); point to `spec-review.json` for the one-line summaries; **do not echo any body**. Surface a `must_ack` (or `review unavailable`) item only if NEW or CHANGED vs the prior promoted `spec-review.json` wave (match by `child`+`summary`); an unchanged item was already acknowledged (anti rubber-stamp). A `review unavailable` item means the gate did not run for that child, so the user's approval explicitly acknowledges it, never a silent clean pass. Additionally present the `ppa.json` content **verbatim** (a few-element numeric array, not a "body"); these are the acceptance targets synthesis/power-analysis will gate on, transcribed by Wave 1 with no other human-visible surface, and the approval covers them.

If `spec_gate.gate==trip`, resolve each `flagged` item in exactly one of three ways. **This is the single home of the waiver protocol:**
- **fixed**: the operator rejects (below) and directs a rework sub-Task back to Step 6.
- **waived (human waiver)**: record a waiver (schema `spec_gate.waived`) whose **`reason` is human-authored: PROMPT the operator and block until provided, never auto-write it**. A waiver keys on **(child, lens)**: one waiver clears every flagged finding of that pair. For a **critical-severity faithfulness** waiver, surface: "no downstream stage re-checks spec-vs-brainstorm, so this is a terminal accept." Waivers reach the envelope only via finalize `--waived`.
- **partition-rooted**: the defect is rooted in the child partition, not a design.md body (`manifest.json` is read-only after the partition gate), so a design.md-only rework cannot clear it; close via early-fail (`requirements need revision`) for a fresh run.

**Approve precondition (finalize re-checks it in-process):** you MUST NOT accept the user's approval unless `spec_gate.gate==clear` OR every `flagged` finding is waived per the waiver protocol above; if not, resolve first.

On reject: route a rework sub-Task, body off the main thread. The rework first clears `spec_gate=clear` (invalidate-on-rework, so a post-clear body edit cannot leave a stale `clear`), then **re-enter the main chain at Step 6** and flows through 6→7→8 again.

### Step 9: Finalize (script, mandatory)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py finalize \
  --workdir {workdir} --module {module} --status <pass|fail> \
  --waived '<spec_gate.waived[] JSON>'
```

You supply only the human-gate outcome: `--status` (approve/reject) and `--waived` (`[]` if none). `ppa_targets` is read from the Wave-1-authored `{workdir}/ppa.json` (pass `--ppa-targets '<JSON>'` only as an explicit override; a missing/invalid `ppa.json` is a BLOCKED program exception, not a silent default). `finalize` (on a pass) re-runs the constraint derivation (divergence-proofing), re-derives the Step-7 `spec_gate` verdict in-process from `spec-review.json` and merges `--waived`, **enforces the Step-8 approve precondition itself** (an unmet precondition downgrades `--status pass` to a written `status=fail`), enumerates `artifacts[]` present-only (design.md / manifest.json / ppa.json / spec-review.json / the N `<child>.md` / `constraints/<TOP>.{sdc,sgdc}` — **never `brainstorm.md`**), and writes the complete `result.json`. Exit 0 = result.json written (status pass or fail); a non-zero exit is a program exception (BLOCKED), not a `status=fail`.

Downstream consumption note: synthesis and power-analysis read `ppa.json` directly as their gate targets; the Orchestrator reads it only to author rtl-design's directive. Nothing is injected into any prompt by this stage.

## Decision Rules

- When specification conflicts with the architecture plan, the `Status=approved` content of `brainstorm.md` takes precedence; if unclear, close via early-fail (`requirements need revision: …`) — you do not brainstorm; recovery is out-of-band, outside this skill.
- Overview (§1.1–1.6) vs submodule (§1.7+) conflict-resolution order is owned by `design-template.md` — see it. (§1.6 ↔ constraint consistency is by-construction: `derive-constraints` generates both files from §1.6.)

## Red Flags

| Excuse | Reality |
|---|---|
| "The design looks complete — I'll mark it pass" without the user's approval at the design.md gate | The design.md gate is architectural, not a formality. Marking pass without it ships an unapproved spec downstream. |
| "Minimum fields look mostly there — pass" | Mark pass only when the required columns of §1.3/§1.4/§1.5/§1.7+ are complete (see the design-template completeness gate table). Partial ≠ pass. |
| "I'll just Edit this wave-output design.md/`<child>.md` body to fix a number" | The main thread holds no body; numerics are locked in the frozen brainstorm. Amend a body only by re-dispatching its wave sub-Task — never by main-thread Edit. |

## Pitfalls

| Mistake | Fix |
|---|---|
| `design.md` drifts from `brainstorm.md` on Features / Scenarios / Clocks. | The overview sections of `design.md` are a canonical derivation from brainstorm; fields must be 1:1 consistent. |

## Completion Gate

- **Step 6 self-checks:** `spec check-coverage` exit 0 AND `spec derive-constraints` exit 0 (both pre-human-gate; the latter re-run by finalize as the divergence-proof invariant).
- **Semantic gate:** the Step-7 `spec_gate` verdict cleared per the Step-8 approve precondition; `stage_specific.spec_gate` written; `spec-review.json` in `artifacts[]`.
- **Human:** the design.md gate is approved (incl. port roles, reset polarity, clock relationships, the presented `ppa.json`) — the engineering-soundness judgment the token check cannot catch.
- **Finalize:** `result.json` was written by `spec finalize` (it owns status / `top_module` / `ppa_targets` / `spec_gate` / `fail_reason` / `artifacts[]`; `<TOP>` = `manifest.module` matches the `constraints/<TOP>.{sdc,sgdc}` stems). You supply only `--status` / `--waived` (+ `--ppa-targets` only as an explicit override; `--fail-reason` on the early-fail exits).
- No Iron Rule or Red Flag was triggered.
- `result.json` written; its verdict is schema-validated externally, not by you.

## Return Contract

**Do not decide what happens after you complete** — control returns directly to the caller; the caller decides based on `result.json`.

### Re-entry and completion

Your sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`; a missing `result.json` is treated as incomplete (no cross-session "already complete" flag). The framework's `carry_self` never carries the gate review (`spec-review.json`) forward on a repair — invalidate-on-rework. Every re-entry re-runs the semantic gate (Step 7) on the current `design.md` (+ per-child) before the Step-8 approve precondition and Step-9 finalize, so a compaction resumes without losing work and a stale `clear` cannot survive to finalize. The two path-handoff gates always re-ask idempotently: re-point the user to the on-disk path and ask them to reconfirm — **do not re-read or re-echo the file body.** `brainstorm.md` is the frozen module-root input verified `Status: approved` by design-flow's entry gate before you run; you never approve or re-approve it.

## Bundled References

- [`references/design-template.md`](references/design-template.md) — design.md section template + minimum field completeness gate table.
- [`references/sdc-template.md`](references/sdc-template.md) — SDC generated-output reference (what `derive-constraints` emits).
- [`references/sgdc-template.md`](references/sgdc-template.md) — SGDC generated-output reference (what `derive-constraints` emits).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema (`schema_version: 1`).
- [`references/spec-review.schema.json`](references/spec-review.schema.json) — gating semantic-review schema (Wave 3, Step 7).
- [`references/decompose-task-contract.md`](references/decompose-task-contract.md) — Wave-1 decompose sub-Task contract (Step 2).
- [`references/spec-review-task-contract.md`](references/spec-review-task-contract.md) — per-child reviewer sub-Task contract (Step 7).
