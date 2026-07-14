---
name: specification
description: Use when writing or reviewing design specification (design.md), defining interfaces or constraints (SDC/SGDC), or updating from rework feedback; not for RTL implementation or verification.
---

# Requirements and Specification Freeze

Your sole responsibility: derive a frozen design source of truth from an approved `asic/{module}/brainstorm.md` — `design.md` (overview §1.1–1.6 + submodule §1.7+) + per-child `<child>.md` + `manifest.json` + `coverage.json` + `ppa.json` + a pair of constraint files (`<TOP>.sdc` / `<TOP>.sgdc`). You are a thin Level-0 dispatcher: three sub-agent waves, two path-handoff gates, deterministic main-thread scripts in between; the brainstorm dialogue lives in the pre-pipeline `brainstorm` skill.

## When to Use

- First-time design.md derivation from an approved brainstorm.md.
- Specification modification on an existing module (a repair round amends design.md only — brainstorm.md is frozen and read-only).
- Reviewing or modifying an existing design.md.
- Creating or updating SDC/SGDC constraint files.

## Iron Rule

Your boundary:

- **Write only under `{workdir}`** (artifacts + `result.json`); never read or write other modules' artifacts. Reading reference material outside `{workdir}` (plugin-internal templates, upstream canonical inputs) is allowed.
- **No brainstorm here.** Consume a frozen `asic/{module}/brainstorm.md` (produced by the pre-pipeline `brainstorm` skill; `design-flow`'s entry gate already verified `Status: approved` — a missing/draft brainstorm means the user must run `Skill(veripower:brainstorm)` first). Run the two path-handoff gates but hold no document body and drive no D0–D7 dialogue.
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

| Path | Schema / Format | Use |
|---|---|---|
| `asic/{module}/brainstorm.md` | Custom markdown; frontmatter `Status: approved` | The frozen module-root input (approval already gate-verified). Read only inside sub-Tasks and passed by path to `check-coverage --brainstorm`; the main thread never loads its body. |

When `{failing_result}` is provided, read it once at its path as reference; a first delivery depends only on existing artifacts under `{workdir}`.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + `framework/references/schemas/envelope.schema.json` | This stage's status contract. |
| `design.md` | Custom markdown (section template in `references/design-template.md`) | Design document (overview §1.1–1.6 + submodule §1.7+). |
| `manifest.json` | Custom JSON (child registry) | Child-partition SSoT (`module`, `children[]` with `name` / `doc` / `rtl_modules[]` / `brainstorm_anchor` / `role`); consumed by simulation-plan / rtl-design / frontend-signoff. |
| `<child>.md × N` | Custom markdown (template in `references/child-design-template.md`) | Per-child sub-design (frontmatter + §1–§5); consumed by rtl-design (§2/§3), simulation-plan (§5), frontend-signoff (§5). |
| `ppa.json` | JSON array `[{dim, target}, …]` | PPA-targets SSoT, authored by Wave 1 from brainstorm D6 (`[]` when none); declared input of synthesis / power-analysis. |
| `constraints/<TOP>.sgdc` | SpyGlass SGDC (template in `references/sgdc-template.md`) | Lint/CDC constraint source of truth (generated by `derive-constraints`). |
| `constraints/<TOP>.sdc` | SDC (template in `references/sdc-template.md`) | Synthesis/STA constraint source of truth (generated by `derive-constraints`). |
| `spec-review.json` | `references/spec-review.schema.json` | Gating per-child semantic review (Wave 3; faithfulness + conformance block, soundness must-acknowledge). |

The promoted full set is enumerated by `spec finalize` — this table is the contract surface, not a mirror of it.

## Workflow

You are loaded on the main thread as a thin Level-0 dispatcher. You hold no document body — `brainstorm.md`, `design.md`, and every `<child>.md` are read/written only inside sub-Task contexts.

### Fan-out Dispatch Contract

Framework-mechanism rules (dispatch-and-wait below is the main-thread lifecycle); enforced at the framework / harness layer (the wake protocol; writes confined to `runs/N/`, promoted on reap), not by this skill's Completion Gate.

- **No Level 2 dispatch:** this skill dispatches only Level-1 sub-Tasks for the three Workflow waves (Wave 1 decompose / Wave 2 per-child sub-designs / Wave 3 semantic reviewers) — the audit boundary.
- **Dispatch-and-wait:** after dispatching a wave's sub-Task(s), send a brief status and end the turn; the harness wakes the main thread per completion. Reap each, and finalize only after all dispatched sub-Tasks have reported — never against a partial set.
- **No `kernel.py`:** this skill does not call `kernel.py`.
- **Sub-Task `STATUS: BLOCKED` carve-out:** a sub-Task's last-line `STATUS: BLOCKED <reason>` is a harness-level signal, distinct from the `result.json.status` enum; the main thread maps it to `status=fail` + `fail_reason` listing failed children (via the finalize early-fail entry) and defers per-child re-dispatch to a later repair dispatch. Edge: if Wave 1 blocked **before `manifest.json` exists** (a first delivery only), finalize exits 2 — the run is reaped `blocked`, which is correct: with no manifest there is nothing to enumerate, a blocked run never promotes, and the kernel's forward path re-dispatches.

### Step 1: Entry — seed, determine scope, pick the entry point

When `{directive_path}` is injected, Read it first — its `fix_locus` narrows the scope. Run `spec seed --workdir {workdir}` (no-clobber carry of the prior canonical; a no-op when no canonical exists — so any freshly-authored workdir residue is kept). Then:

- **A prior run was promoted** (`spec seed` carried a canonical) — a repair round. Scope = `{directive_path}`'s `fix_locus` when injected, else a `{failing_result}`'s `stage_specific` attribution (Read the trigger once; body stays off the main thread; `brainstorm.md` read-only). Dispatch one design.md-level rework sub-Task, then **re-enter the main chain at Step 6 and flow through Steps 7–9**: Steps 2–5 (the partition) are skipped — `manifest.json` is immutable after the partition gate — and Step 7 (the semantic gate) re-runs this pass, so the promoted gate is always fresh. Ends at Step 9.
- **No canonical** (`spec seed` was a no-op) — a first delivery, or an interrupted first delivery whose residue is kept no-clobber: full re-derivation from Step 2 (fresh partition; brainstorm-level rework recovery also lands here). Ends at Step 9.

**Early-fail exit.** Whenever a documented failure below cannot be resolved, close the run with the finalize early-fail entry — never hand-assemble the envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py finalize \
  --workdir {workdir} --module {module} --status fail --fail-reason "<one-line reason>"
```

Reasons used by this skill: `failing_result not readable: <path>`; `requirements need revision: <D-dim>` (a contradiction unfixable without changing the frozen brainstorm — routes to ESCALATE; recovery is out-of-band); `manifest child missing rtl_modules`; `constraint derivation: <table> defect`. finalize enumerates `artifacts[]` present-only, so a seeded workdir's carried **product** set all promotes — an early fail never shrinks it (the judged `spec-review.json` is the one exception: deliberately never carried on rework, per invalidate-on-rework).

### Main chain at a glance

| Step | Executor | Does → produces | On failure |
|---|---|---|---|
| 2 | Wave 1 (sub-Task ×1) | Decompose: `manifest.json` + `design.md` §1.1–1.7 + `ppa.json` | `STATUS: BLOCKED` → Fan-out Contract |
| 3 | script | `derive-ports` → per-child cut-edge port JSON | missing `rtl_modules` → Wave-1 rework; unresolvable → early-fail |
| 4 | human | Partition gate (metadata summary only) | merge feedback → re-dispatch Step 2, re-run Step 3 |
| 5 | Wave 2 (sub-Task ×N) | One `<child>.md` per child | `STATUS: BLOCKED` → Fan-out Contract |
| 6 | script | `check-coverage`; on pass `derive-constraints` (generate + self-check SDC/SGDC) | coverage violations → rework by category, loop until clean; derivation table defect → Wave-1 rework, re-run this step; unresolvable → early-fail |
| 7 | Wave 3 (reviewers ×N) + script | `spec-review.json` + `validate-review` → `{gate, flagged, must_ack}` | `trip` → blocks in place into Step 8 |
| 8 | human | design.md gate (approve precondition lives here) | reject → rework sub-Task → **re-enter Step 6** (flows through 6→7→8 again) |
| 9 | script | `finalize` → `result.json` | non-zero exit = program exception (BLOCKED) |

### Step 2: Wave 1 — decompose (Level-1 sub-Task)

Dispatch one sub-Task that, in its own context, reads `asic/{module}/brainstorm.md` and writes:
   - `manifest.json` — `module`, `children[]` with `name` / `doc` / `rtl_modules[]` (REQUIRED, ≥1) / `brainstorm_anchor` / `role`; optional `shared_subsections[]`.
   - `design.md` §1.1–1.6 overview (incl. §1.4.1 Top-Level IO + §1.4.2 Inter-module Interconnects) + §1.7 submodule index.
   - `ppa.json` — the D6 `ppa_targets` **verbatim** as a JSON array of `{dim, target}` (`[]` when D6 declares none or was not reached). This is the only step that transcribes PPA numbers; everything downstream reads the file.

Child partition follows the interface graph's clean/dirty edges, NOT line counts: cut ONLY at clean elastic-handshake boundaries (`valid/ready` or `req/ack`); skew- or phase-locked couplings are NOT cut points — the modules they bind stay in one child, internalizing that coupling. Each child is thus one or more whole RTL modules forming a coupling cluster bounded by clean handshakes; a tightly-coupled fabric with no clean internal handshake is monolithic (N=1 — only the top boundary is clean). Small leaf modules join their cluster — no line-count floor / size class.

**top-integration carve-out (best-effort hint):** `<TOP>` (= `manifest.module`) should form its own child whose `rtl_modules == [<TOP>]` — do not bundle any logic module into the top child. This is a soft hint; the hard guarantee is `check-coverage`'s purity gate.

The module set (D4) + inter-module wire table (D2b → §1.4.2) come from the frozen brainstorm. Last line: `STATUS: DONE` + paths, or `STATUS: BLOCKED <reason>`.

### Step 3: Derive cut-edge ports (script)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py derive-ports --workdir {workdir}
```

Its small JSON output (`{child: [wire,...]}`) is each child's inter-module ports — the §1.4.2 wires whose Producer/Consumer RTL module is in that child's `rtl_modules`. It is the partition gate's cut-edge summary AND each child's Wave-2 port injection (children never guess inter-module ports; top-level IO ports stay child-authored from §1.4.1, backstopped by `check-coverage`'s `ports ⊆ §1.4.1∪§1.4.2` subset check). On a non-zero exit (stderr names the defect), do NOT gate: route a Wave-1 rework sub-Task to add the missing `rtl_modules[]`, or close via early-fail (`manifest child missing rtl_modules`).

### Step 4: Partition gate (human) — no body read

Present an N-child summary built from `Grep manifest.children[].{name,role}` + the `derive-ports` JSON (cut-edge wires per child). **Do NOT read `design.md` §1.4.x into the main thread** — point the user to §1.4 to inspect themselves. Include an oversize-cluster advisory flag computed from manifest metadata only (`rtl_modules` count + `brainstorm_anchor` line-span as a size proxy) — a sub-Task context-budget hint, NOT a partition criterion (do not let it re-seed size-class thinking). Never auto-split. Confirm, or take merge feedback → re-dispatch Wave 1 with the new grouping → re-run `spec derive-ports`.

### Step 5: Wave 2 — child sub-designs (Level-1 sub-Task ×N)

Dispatch N sub-Tasks (one per child), each writing `{workdir}/<child>.md` per `references/child-design-template.md`. `frontmatter.ports` = the derived cut-edge list (Step 3) for inter-module wires + any child-authored top-IO ports. **Wave 2 is ALWAYS dispatched (N=1 → ×1 sub-Task); a child body never lives on the main thread.** After dispatching all N, end the turn; reap each child on its wake and proceed only after all N have reported.

### Step 6: Coverage gate + constraint derivation (script)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py check-coverage --workdir {workdir} --brainstorm asic/{module}/brainstorm.md
```

It reads brainstorm/children/design in-process and writes `coverage.json` (sub-blocks: `brainstorm_coverage` / `frontmatter_subset` / `token_survival` / `self_containment` / `structure`); exit 0 = pass.

**On failure you fix nothing yourself** — route the (small) verdict to a rework sub-Task by category, then re-run the script, looping until clean:

| Violation category | Rework target |
|---|---|
| `gaps` / `orphans`; `structure` §1.3/§1.5 columns; period (R-B); Clock-Domain (R-F); `purity_violations`; `interconnect_violations` (§1.4.2 Width / Clock Domain); `top_io_driver_violations` (§1.4.1 output Owner) | Wave-1 rework (re-partition the manifest; `design.md` overview tables) |
| `token_survival`; `frontmatter_subset`; `self_containment`; child §5 columns; feature coverage (R-C) | the affected Wave-2 child rework |

You hold only the verdict + the routing decision — never a body.

**On a clean coverage gate, immediately run:**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py derive-constraints --workdir {workdir}
```

It generates the complete `constraints/<TOP>.{sdc,sgdc}` purely from the §1.6 + §1.4.1 tables (clocks + relationships, IO delays, abstract_ports, resets + polarity) and self-checks before writing (Iron Rule: no separate checker). Running it here — before the design.md gate — surfaces table defects the coverage gate cannot see (enum values, reset polarity/kind, clock-name collisions) while a rework still flows naturally through Steps 6→7→8. On a non-zero exit (stderr names the exact defect), route a Wave-1 rework sub-Task and re-run this step; if unresolvable, close via early-fail (`constraint derivation: <table> defect`). `finalize` re-runs the derivation at Step 9 as the divergence-proof invariant (`<TOP>` ← `manifest.module`), so the files the human approved and the files that ship cannot diverge.

### Step 7: Wave 3 — semantic review (gating)

You run this wave after Step 6 is fully clean and before the design.md gate, on **every** pass through the main chain. Dispatch Wave 3 — **N per-child Level-1 reviewers** (one per `manifest.children[]`) per `references/spec-review-task-contract.md`, paths only: you read no body. Lens definitions, the gating split (`faithfulness`/`conformance` block; `soundness` advisory), and scope boundaries live in that contract — do not restate or reinterpret them here.

> **Gate semantics (block-in-place).** A `gate=trip` does **NOT** write `status=fail` and does **NOT** route out of the stage: it blocks `status=pass` **in place** and surfaces findings into the design.md gate (Step 8). Never a fail-out verdict.

Aggregate the reaped reports into `{workdir}/spec-review.json` (schema `references/spec-review.schema.json`):
- `STATUS: DONE` + valid finding JSON → fold its findings in, stamping each with its reporting `child` (the reviewer carries `child` only at top level; the schema requires it per finding).
- `STATUS: BLOCKED` OR malformed/unparseable JSON → record one `{child, lens:"unavailable", severity:"minor", location:"-", summary:"review unavailable: <reason>"}` finding.
- `verdict="concerns"` iff any finding with `lens ≠ unavailable`; `has_critical` iff any `severity=critical`.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py validate-review --review {workdir}/spec-review.json
```

On a non-zero exit, re-assemble the JSON and re-run (a main-thread fix, NOT a re-dispatch). On exit 0 it prints the gate verdict `{"gate":"trip"|"clear","flagged":[{child,lens,severity}…],"must_ack":[{child,severity}…]}` — the mechanical `lens × severity` reduction, computed by the script, not by eye. You copy nothing into any envelope: finalize re-derives this same verdict in-process from the promoted `spec-review.json` (which the resume-guard also re-reads). Apply it — **this section is the single home of the waiver protocol**:

- **`clear`** → proceed; carry `must_ack` into Step 8, **deduped**: surface an advisory item only if NEW or CHANGED vs the prior promoted `spec-review.json` wave (match by `child`+`summary`) — an unchanged item was already acknowledged (anti rubber-stamp).
- **`trip`** → each `flagged` item is resolved in exactly one of three ways:
  - **fixed** — the operator directs a rework sub-Task (handled as a Step-8 reject: body off the main thread, back to Step 6); or
  - **waived (human waiver)** — record `{child, lens, location, classification ∈ {false-positive, accepted-risk}, reason}`. **The `reason` is human-authored: PROMPT the operator and block until provided — never auto-write it.** A waiver pairs on **(child, lens)**; `location` is archival only — one waiver clears every flagged finding of that (child, lens). No round counter, no cross-round matching, no auto-downgrade. For a **critical-severity faithfulness** waiver, surface: "no downstream stage re-checks spec-vs-brainstorm — this is a terminal accept." Waivers reach the envelope only via finalize `--waived`.
  - **partition-rooted** (defect rooted in the child partition, not a design.md body — `manifest.json` is read-only after the partition gate): a design.md-only rework cannot clear it; close via early-fail (`requirements need revision`) for a fresh run.
- **Wave unusable** → write a minimal `spec-review.json` with a single `unavailable` finding (the validator reports `gate=clear`), and surface "review unavailable" as a **must-acknowledge** item at Step 8 (deduped likewise) — the user's approval explicitly acknowledges the gate did not run; never silently a clean pass.

### Step 8: design.md gate (human)

Path-handoff: give the user the `design.md` (+ per-child) paths + the `coverage.json` verdict + the `spec-review.json` verdict — `spec_gate.flagged` blocking items + `spec_gate.must_ack` advisory items (deduped per Step 7) + any `review unavailable` ack item; point to `spec-review.json` for the one-line summaries; **do not echo any body**. Additionally present the `ppa.json` content **verbatim** (a few-element numeric array, not a "body") — these are the acceptance targets synthesis/power-analysis will gate on, transcribed by Wave 1 with no other human-visible surface; the approval covers them.

**Approve precondition (the single home — finalize re-checks it in-process):** you MUST NOT accept the user's approval unless `spec_gate.gate==clear` OR every `flagged` finding is waived per Step 7's waiver protocol; if not, resolve at Step 7 first.

On reject: route a rework sub-Task (body stays off the main thread; the rework first clears `spec_gate=clear` — invalidate-on-rework, so a post-clear body edit cannot leave a stale `clear`), then **re-enter the main chain at Step 6** and flow through 6→7→8 again.

### Step 9: Finalize (script, mandatory)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/spec/__main__.py finalize \
  --workdir {workdir} --module {module} --status <pass|fail> \
  --waived '<spec_gate.waived[] JSON>'
```

You supply only the human-gate outcome: `--status` (approve/reject) and `--waived` (`[]` if none). `ppa_targets` is read from the Wave-1-authored `{workdir}/ppa.json` (pass `--ppa-targets '<JSON>'` only as an explicit override; a missing/invalid `ppa.json` is a BLOCKED program exception, not a silent default). `finalize` (on a pass) re-runs the constraint derivation (divergence-proofing), re-derives the Step-7 `spec_gate` verdict in-process from `spec-review.json` and merges `--waived`, **enforces the Step-8 approve precondition itself** (an unmet precondition downgrades `--status pass` to a written `status=fail`), enumerates `artifacts[]` present-only (design.md / manifest.json / coverage.json / ppa.json / spec-review.json / the N `<child>.md` / `constraints/<TOP>.{sdc,sgdc}` — **never `brainstorm.md`**), and writes the complete `result.json`. Exit 0 = result.json written (status pass or fail); a non-zero exit is a program exception (BLOCKED), not a `status=fail`.

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

Your sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`; a missing `result.json` is treated as incomplete (no cross-session "already complete" flag). `spec seed` never clobbers workdir residue but never carries the gate review (`spec-review.json`) forward — invalidate-on-rework. Every re-entry re-runs the semantic gate (Step 7) on the current `design.md` (+ per-child) before the Step-8 approve precondition and Step-9 finalize, so a compaction resumes without losing work and a stale `clear` cannot survive to finalize. The two path-handoff gates always re-ask idempotently: re-point the user to the on-disk path and ask them to reconfirm — **do not re-read or re-echo the file body.** `brainstorm.md` is the frozen module-root input verified `Status: approved` by design-flow's entry gate before you run; you never approve or re-approve it.

## Bundled References

- [`references/design-template.md`](references/design-template.md) — design.md section template + minimum field completeness gate table.
- [`references/sdc-template.md`](references/sdc-template.md) — SDC generated-output reference (what `derive-constraints` emits).
- [`references/sgdc-template.md`](references/sgdc-template.md) — SGDC generated-output reference (what `derive-constraints` emits).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema (`schema_version: 1`).
- [`references/spec-review.schema.json`](references/spec-review.schema.json) — gating semantic-review schema (Wave 3, Step 7).
- [`references/spec-review-task-contract.md`](references/spec-review-task-contract.md) — per-child reviewer sub-Task contract (Step 7).
