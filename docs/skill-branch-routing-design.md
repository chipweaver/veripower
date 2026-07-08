# `skill-branch-routing-design.md` — Step 1 routing design

## 1. Scope

This document governs how every skill's Workflow field expresses its Step 1 routing without exposing a `mode` parameter. Audience: skill authors writing Workflow Step 1. Companion: `skill-field-contract-design.md` §4.3.7 (Workflow field rule).

## 2. Background

Every stage faces three logical paths: (1) **first-run** — initial dispatch, no prior artifacts on disk; (2) **explicit rework** — caller injects `{rework_trigger}` pointing at a failed downstream `result.json` with a `violations[]` payload; (3) **cascade rework** — caller re-dispatches without a trigger; the stage detects prior artifacts on disk and updates incrementally.

The design problem is to express all three paths without a `mode` parameter that would require per-form branching from the caller. The solution is a two-signal read performed entirely inside Step 1. For the English field-title convention see `skill-field-contract-design.md` §3.5 (F5).

## 3. Principles

### 3.1 P1 — Two-signal routing

Step 1 routing uses exactly two signals: `{rework_trigger}` injection (yes / no) × disk-prev-artifact existence (yes / no). No other signals. Skills do NOT self-scan disk beyond prev-artifact presence, and do NOT consult `task.json`, `events.jsonl`, or any external state.

### 3.2 P2 — Step-1-only routing

The branch decision happens once, in Step 1. Subsequent steps describe a single flow with scope-limiting language (e.g., *"trigger-driven path: scope limited to files listed in `trigger.violations[]`"*). Multi-step branching is a code smell — collapse into Step 1.

### 3.3 P3 — Branch coverage = step coverage

If Step 1 produces N branches, downstream steps MUST address how each branch threads through them, OR state *"Steps 2–N are identical across branches; they differ only in scope."* Linear downstream after a multi-branch Step 1 is a bug — the implementer cannot reconstruct what each branch does.

### 3.4 P4 — Idempotency by design

The disk is the source of truth for artifacts, not for progress. Do NOT track partial completion via custom disk markers. Trust `result.json` presence and the canonical-vs-`runs/` promotion owned by `framework/scripts/state.py`.

### 3.5 P5 — Fail-closed semantics

If `{rework_trigger}` is injected but unreadable or malformed, write `result.json` with `status=fail` and a `fail_reason` identifying the unreadable path. Do NOT silently fall back to first-run.

**Rationale:** Silent fallback masks caller-side bugs as completed first-runs.

## 4. Two-signal table and walk-throughs

| `{rework_trigger}` | Disk prev artifacts | Path | Step-1 behavior |
|---|---|---|---|
| not injected | not present | first-run | full generation from spec |
| not injected | present | cascade rework | incremental update; diff against prev artifacts, re-run affected scope |
| injected | present (typical) | explicit rework | scope limited to `trigger.violations[]`; non-listed files untouched |
| injected | not present | rare; treat as explicit rework | scope limited to `trigger.violations[]`; full generation for non-listed files if absent |

**Worked walk-through: standard worker (3-branch)** — lint-cdc archetype:

```text
Step 1: Read inputs.
  if {rework_trigger} injected:
    open trigger.path — if unreadable → result.json status=fail,
      fail_reason="rework_trigger not readable: <path>"; STATUS: DONE
    read trigger.stage_specific.violations[]; build fix list → explicit rework
  elif prev-artifact present in {workdir}:
    diff against upstream result.json → cascade rework
  else: first-run

Step 2: make <target>
  explicit rework: limit to fix-list files
  cascade rework:  limit to diff scope
  first-run:       full generation

Step 3: write result.json (status/artifacts/metrics); STATUS: DONE
```

`simulation-plan` extends the three worker branches with a fourth, session-resume, giving: trigger-driven / session-resume / cascade rework / first-run. That fourth branch — its trigger condition, resume-from-last-gate mechanism, and why dialogue stages use it — is the §6.3 carve-out.

**Note:** §5 (Examples) is intentionally absent. The walk-through above absorbs that role within §4. Section numbers are preserved to match the template positions used across the design-doc set.

## 6. Carve-out catalog

Six skills deviate from the standard 3-branch worker pattern. Each must reference its carve-out in the Workflow rationale.

### 6.1 Never-trigger-target (power-analysis)

`power-analysis` is never a rework-DAG fix target; callers never inject `{rework_trigger}`. Fix-scope context arrives via `{orchestrator_context_path}` (read-only hint). Step 1 has no trigger-driven branch — first-run and cascade rework only. (`skills/power-analysis/SKILL.md` Workflow rationale.)

### 6.2 Terminal stage (frontend-signoff)

`frontend-signoff` has no rework path. All predecessors must be `pass`; any non-pass aborts with `status=fail`. Step 1 is linear — a pre-flight check, not a branch. (`skills/frontend-signoff/SKILL.md` Workflow rationale.)

### 6.3 Dialogue 4-branch (simulation-plan)

`simulation-plan` adds session-resume as a fourth branch: `{workdir}/verification-plan.md` present but `result.json` absent signals a paused multi-turn review; the stage resumes from the last gate rather than re-deriving incrementally. (`skills/simulation-plan/SKILL.md` Workflow rationale.)

### 6.4 Session-resume replaces incremental (specification)

`specification` uses session-resume on the disk-prev-artifact-present branch instead of incremental update. No external reference diff exists to anchor re-derivation; the only meaningful action is to continue the dialogue from its last gate. (`skills/specification/SKILL.md` Workflow rationale.)

### 6.5 Analyzer exception (simulation-triage)

`simulation-triage` receives only identifying coordinates in the dispatch prompt (`{module}` + the failed run number) and self-reads everything else from canonical disk. It has no `{workdir}`, no `{rework_trigger}`, no disk-prev-artifact concept. The two-signal model does not apply. (`skills/simulation-triage/SKILL.md` Input Artifacts.)

### 6.6 Never-trigger-target / read-only re-verifier (timing-analysis)

`timing-analysis` is never a rework-DAG fix target: `route.py` never returns it (on a `ppa` failure it routes away to rtl-design/specification; `_PPA_STAGES`), and the orchestrator attaches `{rework_trigger}` only on a `REWORK` action to its target. It runs only by forward `DISPATCH`, which carries no trigger — the same archetype as §6.1 (power-analysis), but simpler: it consumes no `{orchestrator_context_path}` hint either, because it is read-only w.r.t. `Design/synthesis/` and cannot fix anything. Step 1 is a single linear pre-flight check (synthesis `status=pass` + netlist/SDC present); no trigger / incremental / first-run fork. P5 (fail-closed on unreadable trigger) does not apply — no trigger is ever delivered. (`skills/timing-analysis/SKILL.md` Workflow rationale.)

## 8. Process for changing

When a stage's branching shape evolves, coordinate with `framework/scripts/state.py` `PREREQ_OF` if input vectors change. If the new shape does not fit an existing §6 carve-out, add a new subsection and reference it from the affected skill's Workflow rationale before merging.
