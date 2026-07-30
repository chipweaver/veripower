# `skill-branch-routing-design.md` — Step 1 routing design

## 1. Scope

This document governs how every skill's Workflow field expresses its Step 1 without exposing a `mode` parameter. Audience: skill authors writing Workflow Step 1. Companion: `skill-field-contract-design.md` §4.3.7 (Workflow field rule).

## 2. Background

Step 1 is **not** a branch selection. It is one linear flow — **bootstrap → determine scope → minimal-edit** — because the fork that was once modelled as branches (first-run vs a re-run that carries prior products) is resolved before Step 1 ever runs: the kernel's `store.carry_self` copies the author's own previous canonical products into the fresh workdir at dispatch (a no-op on a genuine first run, when no canonical exists yet). For the tool stages, the `bootstrap` verb separately deploys the workdir no-clobber (abort if already deployed) within Step 1, preserving whatever `carry_self` already placed there. What differs between runs is only the **scope** of the edit, which Step 1 reads from one file.

Compaction-safe resume is a kernel/architecture property (`ARCHITECTURE.md`, "Compaction-safe resume"), not a per-skill feature: a fresh `runs/N` workdir per dispatch + the kernel's `carry_self` before Step 1 + a no-clobber `bootstrap` deploy within Step 1 (for the tool stages) + `result.json` as the sole completion signal make re-entry automatic. No skill needs "session-resume" prose.

## 3. Principles

### 3.1 P1 — Scope from one file, no `mode` parameter

Step 1 reads this round's scope from `{workdir}/dispatch.json`, which the kernel writes at dispatch. There is no ladder over hint channels, and therefore no branch on *which* channel arrived — the earlier three-channel arrangement is what made Step 1 look like a mode selection in the first place.

```
scope = dispatch.json.scope        ∪  dispatch.json.caused_by
        # paths/anchors that            # the failing runs' own result.json;
        # narrow this round             # read each, narrow to what it attributes
      —— neither key present ——
      → decide on {workdir}: the skill's own prior products are there
        (a re-verify: re-derive the gate, rewrite nothing)
        or they are not (a first delivery: everything)
```

The two narrowing keys are a **union**, not a priority order: `scope` is what the kernel computed (drifted inputs, plus any diagnosis's `fix_locus`), `caused_by` is what a failing envelope attributes, and a round may legitimately carry both. `dispatch.json` also carries `reasons` when a human authored the diagnosis behind this repair; that is judgment, not scope, and it outranks the skill's own reading of the files.

No skill self-scans `events.jsonl` or any external state. Its only disk reads are the declared inputs (at their `dispatch.json`-injected locations), `dispatch.json` itself, and a `bootstrap`-style deploy verb's own probe of `{workdir}` for already-carried residue.

### 3.2 P2 — Scope decided once, in Step 1

The scope is fixed once, in Step 1. Subsequent steps describe a single flow with scope-limiting language (e.g. *"the SDC edits stay confined to the scope set in Step 1"*), never a re-branch. Multi-step branching is a code smell.

### 3.3 P3 — Scope threads as scope, not as branches

Downstream steps run in the same order regardless of scope and differ only in *what* they touch. State this explicitly (*"Steps 2–N are identical regardless of scope; a narrowed scope limits the edit, a first delivery covers everything"*) so an implementer cannot mistake scope for control flow.

### 3.4 P4 — Idempotency by design

The disk is the source of truth for artifacts, not for progress. Do NOT track partial completion via custom disk markers. `result.json` presence is the sole completion signal; the fresh-workdir-per-dispatch and canonical-vs-`runs/` promotion are owned by `framework/scripts/kernel.py`. The kernel's `carry_self` runs once, before Step 1, and `bootstrap`-style deploy verbs are no-clobber, so a re-entry keeps freshly-authored residue automatically.

### 3.5 P5 — A narrowing key is a fact, not a hint to validate

Every path in `scope` / `caused_by` was resolved by the kernel before the run was allocated: a dangling `--caused-by` or an unknown `--diagnosis-refs` is rejected at dispatch, so no run ever starts holding an unreadable one. Read them for content; do not re-classify readability, and do not write a "not readable" early-fail branch for them. The pre-flight checks a skill *does* own are its declared inputs (`fail_reason="external reference missing: <path>"`), which are canonical artifacts the kernel does not re-verify at dispatch.

**Rationale:** the previous fail-closed rule existed because a caller hand-assembled the path. It no longer does, and keeping a check for an impossible state costs a branch in five skills.

## 4. The scope shape in practice

One shape, all stages. What differs is only which keys a stage can ever receive:

| Keys a stage can receive | Stages | Notes |
|---|---|---|
| `scope` · `caused_by` | rtl-design, synthesis, simulation, specification, simulation-plan | route-DAG fix targets: an upstream failure can name them |
| `scope` only | lint-cdc, power-analysis | never a route-DAG fix target, so no failure ever names them (§6.1) |
| neither | timing-analysis | read-only re-verifier; nothing to narrow (§6.2) |

**Worked walk-through — a route-DAG worker** (rtl-design / synthesis archetype):

```text
Step 1: Read inputs at their dispatch.json-injected locations (the skill's own
        prior products are already carried in, or genuinely absent on a first
        delivery). Run bootstrap where the archetype has one (no-clobber —
        deploys only what's missing, so carried residue survives).
        scope = dispatch.json.scope ∪ what its caused_by envelopes attribute
             — neither key → prior products on disk ? re-verify only : ALL
Step 2..N: run in the same order; edits stay confined to scope
           (a first delivery covers everything).
Last step: finalize → result.json; STATUS: DONE
```

**Note:** §5 (Examples) is intentionally absent; the walk-through above absorbs that role. Section numbers are preserved to match the design-doc set.

## 6. Carve-out catalog

Most stages are the scope worker of §4. These deviate:

### 6.1 Never-a-fix-target (power-analysis, lint-cdc)

Never a rework-DAG fix target — `route.py` never returns them, so no failure is ever attributed to them and `dispatch.json` never carries a `caused_by`. Only `scope` narrows them. (Workflow rationale in each skill.)

### 6.2 Read-only re-verifier (timing-analysis)

Read-only — cannot author or fix anything, so there is nothing to carry forward and no scope to narrow: Step 1 is a linear pre-flight check and every run re-verifies everything. `route.py` never returns it, and it reads no narrowing key. (Workflow rationale in each skill.)

### 6.3 Post-partition entry point (specification)

A repair round re-enters at the post-partition step, **skipping the human partition gate** — `manifest.json` is immutable after it — and always flows through the semantic gate, so the promoted gate stays fresh. It tells a repair round from a first delivery on its own product, not on a narrowing key: a `<child>.md` in `{workdir}` is Wave-2 output, written only after the partition gate, so its presence proves the partition was gate-confirmed in a prior round. A first delivery runs the full partition from the top. (`skills/specification/SKILL.md` Step 1.)

### 6.4 Content-hash fork (simulation) — retired

`simulation` no longer forks on content hash. The `sim classify-delta` verb and its `first-run`/`freeze`/`patch` branches were retired when self-carry became kernel-performed: `store.carry_self` copies the author's previous TB into the fresh workdir at dispatch, before Step 1 runs, so every round is homogeneous and the skill never branches on whether a TB was carried. `simulation` is now an ordinary scope worker (§4). (`skills/simulation/SKILL.md` Step 1.)

### 6.5 Analyzer exception (simulation-triage)

`simulation-triage` receives identifying coordinates (`{module}` + `sim_run`, the failed run number) as dispatch params. The kernel resolves `sim_run` and every declared input (`design`, `rtl`, `plan`) to their absolute canonical stage roots and writes them into `{workdir}/dispatch.json` at dispatch — triage reads from those injected locations and never self-navigates a module-relative path. It DOES have a `{workdir}` (for its own `result.json` and, on L2, `experiment/`); it reads no narrowing key — every dispatch is a full graduated (L1 → L2) analysis of its one target run. (`skills/simulation-triage/SKILL.md` Input Artifacts.)

## 8. Process for changing

When a stage's Step-1 shape evolves, coordinate with `framework/scripts/rules.py` (the dependency graph is derived from each rule's input/output artifact selectors) if input vectors change. A new per-dispatch fact is a new key in `dispatch.json` (`store.write_dispatch`), never a new prompt variable — and it earns that key only if the executor could not derive it itself. If the new shape does not fit §4 or an existing §6 carve-out, add a subsection and reference it from the affected skill's Workflow rationale before merging.
