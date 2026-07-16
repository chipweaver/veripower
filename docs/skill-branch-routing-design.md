# `skill-branch-routing-design.md` — Step 1 routing design

## 1. Scope

This document governs how every skill's Workflow field expresses its Step 1 without exposing a `mode` parameter. Audience: skill authors writing Workflow Step 1. Companion: `skill-field-contract-design.md` §4.3.7 (Workflow field rule).

## 2. Background

Step 1 is **not** a branch selection. It is one linear flow — **bootstrap → determine scope → minimal-edit** — because the fork that was once modelled as branches (first-run vs a re-run that carries prior products) is resolved before Step 1 ever runs: the kernel's `store.carry_self` copies the author's own previous canonical products into the fresh workdir at dispatch (a no-op on a genuine first run, when no canonical exists yet). For the tool stages, the `bootstrap` verb separately deploys the workdir no-clobber (abort if already deployed) within Step 1, preserving whatever `carry_self` already placed there. What differs between runs is only the **scope** of the edit, which Step 1 reads from a fallback ladder.

Compaction-safe resume is a kernel/architecture property (`ARCHITECTURE.md`, "Compaction-safe resume"), not a per-skill feature: a fresh `runs/N` workdir per dispatch + the kernel's `carry_self` before Step 1 + a no-clobber `bootstrap` deploy within Step 1 (for the tool stages) + `result.json` as the sole completion signal make re-entry automatic. No skill needs "session-resume" prose.

## 3. Principles

### 3.1 P1 — Scope from a ladder, no `mode` parameter

Step 1 determines this round's edit scope from the first available source:

```
scope = {directive_path}.fix_locus       # Orchestrator's fix-scope hint — authoritative
      ?? {failing_result}.attribution    # a repair dispatch's violations[] / attribution
      ?? diff(inputs, prior baseline)    # a re-run whose upstream inputs changed
      ?? ALL                             # a first delivery (nothing narrows it)
```

Each skill lists only the sources it actually has (see §4/§6). No skill self-scans `events.jsonl` or any external state; the only disk reads are the declared inputs (at their `inputs.json`-injected locations), `{workdir}/changed-inputs.md` when the kernel wrote one, and a `bootstrap`-style deploy verb's own probe of `{workdir}` for already-carried residue.

### 3.2 P2 — Scope decided once, in Step 1

The scope is fixed once, in Step 1. Subsequent steps describe a single flow with scope-limiting language (e.g. *"the SDC edits stay confined to the scope set in Step 1"*), never a re-branch. Multi-step branching is a code smell.

### 3.3 P3 — Scope threads as scope, not as branches

Downstream steps run in the same order regardless of scope and differ only in *what* they touch. State this explicitly (*"Steps 2–N are identical regardless of scope; a narrowed scope limits the edit, a first delivery covers everything"*) so an implementer cannot mistake scope for control flow.

### 3.4 P4 — Idempotency by design

The disk is the source of truth for artifacts, not for progress. Do NOT track partial completion via custom disk markers. `result.json` presence is the sole completion signal; the fresh-workdir-per-dispatch and canonical-vs-`runs/` promotion are owned by `framework/scripts/kernel.py`. The kernel's `carry_self` runs once, before Step 1, and `bootstrap`-style deploy verbs are no-clobber, so a re-entry keeps freshly-authored residue automatically.

### 3.5 P5 — Fail-closed on an unreadable repair input

If `{failing_result}` is injected but unreadable or malformed, write `result.json` with `status=fail` and a `fail_reason` identifying the path (`"failing_result not readable: <path>"`). Do NOT silently fall back to a first delivery.

**Rationale:** Silent fallback masks caller-side bugs as completed first deliveries.

## 4. The scope ladder in practice

| Live scope-sources | Stages | Notes |
|---|---|---|
| directive · failing_result · diff · ALL | rtl-design, synthesis, simulation | full ladder — route-DAG fix targets with a diffable upstream |
| directive · failing_result · ALL | specification | no diff arm — `brainstorm.md` is frozen; a repair round enters at the post-partition step (§6.3) |
| directive · diff · ALL | lint-cdc, power-analysis | no `failing_result` arm — never a route-DAG fix target (§6.1) |
| ALL only | timing-analysis | read-only re-verifier; nothing to carry forward, scope is always everything (§6.2) |

**Worked walk-through — a route-DAG worker** (rtl-design / synthesis archetype):

```text
Step 1: Read inputs (already carried in by the kernel's `carry_self` before
        dispatch, or genuinely absent on a first delivery). Run bootstrap where
        the archetype has one (no-clobber — deploys only what's missing, so
        carried residue survives).
        scope = directive.fix_locus
             ?? failing_result.violations[]   (if unreadable → result.json
                status=fail, fail_reason="failing_result not readable: <path>")
             ?? upstream diff
             ?? ALL
Step 2..N: run in the same order; edits stay confined to scope
           (a first delivery covers everything).
Last step: finalize → result.json; STATUS: DONE
```

**Note:** §5 (Examples) is intentionally absent; the walk-through above absorbs that role. Section numbers are preserved to match the design-doc set.

## 6. Carve-out catalog

Most stages are the scope-ladder worker of §4. These deviate:

### 6.1 Never-a-fix-target (power-analysis, lint-cdc)

Never a rework-DAG fix target — `route.py` never returns them, so callers never inject `{failing_result}`. Fix-scope context, when any, arrives via `{directive_path}`; the ladder drops the `failing_result` arm (`directive ?? diff ?? ALL`). (Workflow rationale in each skill.)

### 6.2 Read-only re-verifier (timing-analysis)

Read-only — cannot author or fix anything, so there is nothing to carry forward and no scope to narrow: Step 1 is a linear pre-flight check and every run re-verifies everything (`scope ≡ ALL`). `route.py` never returns them; P5 does not apply (no `{failing_result}` is ever delivered). (Workflow rationale in each skill.)

### 6.3 Post-partition entry point (specification)

`specification` has no diff arm (`brainstorm.md` is frozen). A repair round (a `{failing_result}` or a `{directive_path}` fix) re-enters at the post-partition step, **skipping the human partition gate** — `manifest.json` is immutable after it — and always flows through the semantic gate, so the promoted gate stays fresh. A first delivery runs the full partition from the top. (`skills/specification/SKILL.md` Step 1.)

### 6.4 Content-hash fork (simulation) — retired

`simulation` no longer forks on content hash. The `sim classify-delta` verb and its `first-run`/`freeze`/`patch` branches were retired when self-carry became kernel-performed: `store.carry_self` copies the author's previous TB into the fresh workdir at dispatch, before Step 1 runs, so every round is homogeneous and the skill never branches on whether a TB was carried. `simulation` is now an ordinary scope-ladder worker (§4, full-ladder row) — `{failing_result}` narrows scope exactly as it does for rtl-design/synthesis. (`skills/simulation/SKILL.md` Step 1.)

### 6.5 Analyzer exception (simulation-triage)

`simulation-triage` receives identifying coordinates (`{module}` + `sim_run`, the failed run number) as dispatch params. The kernel resolves `sim_run` and every declared input (`design`, `rtl`, `plan`) to their absolute canonical stage roots and writes them to `{workdir}/inputs.json` at dispatch — triage reads from those injected locations and never self-navigates a module-relative path. It DOES have a `{workdir}` (for its own `result.json` and, on L2, `experiment/`); it has no `{failing_result}` and no scope ladder — every dispatch is a full graduated (L1 → L2) analysis of its one target run. (`skills/simulation-triage/SKILL.md` Input Artifacts.)

## 8. Process for changing

When a stage's Step-1 shape evolves, coordinate with `framework/scripts/rules.py` (the dependency graph is derived from each rule's input/output artifact selectors) if input vectors change. If the new shape does not fit §4 or an existing §6 carve-out, add a subsection and reference it from the affected skill's Workflow rationale before merging.
