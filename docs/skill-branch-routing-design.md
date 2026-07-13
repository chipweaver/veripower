# `skill-branch-routing-design.md` — Step 1 routing design

## 1. Scope

This document governs how every skill's Workflow field expresses its Step 1 without exposing a `mode` parameter. Audience: skill authors writing Workflow Step 1. Companion: `skill-field-contract-design.md` §4.3.7 (Workflow field rule).

## 2. Background

Step 1 is **not** a branch selection. It is one linear flow — **seed/bootstrap → determine scope → minimal-edit** — because the fork that was once modelled as branches (first-run vs a re-run that carries prior products) lives *inside* the `seed` verb (whitelist no-clobber carry; a no-op when no canonical exists) or, for the tool stages, the `bootstrap` verb (deploy the workdir; abort if already deployed). What differs between runs is only the **scope** of the edit, which Step 1 reads from a fallback ladder.

Compaction-safe resume is a kernel/architecture property (`ARCHITECTURE.md`, "Compaction-safe resume"), not a per-skill feature: a fresh `runs/N` workdir per dispatch + no-clobber `seed`/`bootstrap` + `result.json` as the sole completion signal make re-entry automatic. No skill needs "session-resume" prose.

## 3. Principles

### 3.1 P1 — Scope from a ladder, no `mode` parameter

Step 1 determines this round's edit scope from the first available source:

```
scope = {directive_path}.fix_locus       # Orchestrator's fix-scope hint — authoritative
      ?? {failing_result}.attribution    # a repair dispatch's violations[] / attribution
      ?? diff(inputs, seeded baseline)    # a re-run whose upstream inputs changed
      ?? ALL                             # a first delivery (nothing narrows it)
```

Each skill lists only the sources it actually has (see §4/§6). No skill self-scans `events.jsonl` or any external state; the only disk reads are the declared inputs plus the seed's own canonical check.

### 3.2 P2 — Scope decided once, in Step 1

The scope is fixed once, in Step 1. Subsequent steps describe a single flow with scope-limiting language (e.g. *"the SDC edits stay confined to the scope set in Step 1"*), never a re-branch. Multi-step branching is a code smell.

### 3.3 P3 — Scope threads as scope, not as branches

Downstream steps run in the same order regardless of scope and differ only in *what* they touch. State this explicitly (*"Steps 2–N are identical regardless of scope; a narrowed scope limits the edit, a first delivery covers everything"*) so an implementer cannot mistake scope for control flow.

### 3.4 P4 — Idempotency by design

The disk is the source of truth for artifacts, not for progress. Do NOT track partial completion via custom disk markers. `result.json` presence is the sole completion signal; the fresh-workdir-per-dispatch and canonical-vs-`runs/` promotion are owned by `framework/scripts/kernel.py`. `seed`/`bootstrap` are no-clobber, so a re-entry keeps freshly-authored residue automatically.

### 3.5 P5 — Fail-closed on an unreadable repair input

If `{failing_result}` is injected but unreadable or malformed, write `result.json` with `status=fail` and a `fail_reason` identifying the path (`"failing_result not readable: <path>"`). Do NOT silently fall back to a first delivery.

**Rationale:** Silent fallback masks caller-side bugs as completed first deliveries.

## 4. The scope ladder in practice

| Live scope-sources | Stages | Notes |
|---|---|---|
| directive · failing_result · diff · ALL | rtl-design, synthesis | full ladder — route-DAG fix targets with a diffable upstream |
| directive · failing_result · ALL | specification | no diff arm — `brainstorm.md` is frozen; a repair round enters at the post-partition step (§6.3) |
| directive · diff · ALL | lint-cdc, power-analysis | no `failing_result` arm — never a route-DAG fix target (§6.1) |
| ALL only | timing-analysis, frontend-signoff | read-only re-verifier / aggregator; no product seed, scope is always everything (§6.2) |

**Worked walk-through — a route-DAG worker** (rtl-design / synthesis archetype):

```text
Step 1: Read inputs. Run seed/bootstrap (canonical-present vs first-delivery is
        internal to the verb; no-clobber keeps any residue).
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

### 6.2 Terminal / read-only re-verifier (frontend-signoff, timing-analysis)

Read-only — cannot author or fix anything, so there is nothing to seed and no scope to narrow: Step 1 is a linear pre-flight check and every run re-verifies everything (`scope ≡ ALL`). `route.py` never returns them; P5 does not apply (no `{failing_result}` is ever delivered). (Workflow rationale in each skill.)

### 6.3 Post-partition entry point (specification)

`specification` has no diff arm (`brainstorm.md` is frozen). A repair round (a `{failing_result}` or a `{directive_path}` fix) re-enters at the post-partition step, **skipping the human partition gate** — `manifest.json` is immutable after it — and always flows through the semantic gate, so the promoted gate stays fresh. A first delivery runs the full partition from the top. (`skills/specification/SKILL.md` Step 1.)

### 6.4 Content-hash fork (simulation)

`simulation` is the one stage with a genuine Step-1 fork, and it is **not** the scope ladder: `sim classify-delta` hashes the plan + scaffold against the promoted baseline and returns `first-run` / `freeze` / `patch`. `freeze` (inputs byte-identical) dispatches a distinct child that copies the prior TB verbatim and byte-carries its judged `conformance-review.json` for `pin` survival; `patch` reconciles only what the plan changed. The classifier is trigger-agnostic — `{failing_result}` never selects the fork, it only narrows scope within `patch`. (`skills/simulation/SKILL.md` Step 1.)

### 6.5 Analyzer exception (simulation-triage)

`simulation-triage` receives only identifying coordinates (`{module}` + the failed run number) and self-reads everything else from canonical disk. It has no `{workdir}`, no `{failing_result}`, no scope ladder. (`skills/simulation-triage/SKILL.md` Input Artifacts.)

## 8. Process for changing

When a stage's Step-1 shape evolves, coordinate with `framework/scripts/rules.py` (the dependency graph is derived from each rule's input/output artifact selectors) if input vectors change. If the new shape does not fit §4 or an existing §6 carve-out, add a subsection and reference it from the affected skill's Workflow rationale before merging.
