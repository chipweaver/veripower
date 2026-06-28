# skill-structure-design.md — skill containment + references organization

## 1. Self-containment

### Background

VeriPower's DAG topology and dispatch logic are owned exclusively by `design-flow`.
Individual stage skills, in contrast, describe a bounded operation: what they receive, what
they produce, and what they decide internally. They do not describe DAG position, who calls
them, or how their failures are routed. DAG-agnostic descriptions stay composable and
replaceable — topology can evolve without touching stage content.

### Principle — describe self, not orchestration

A stage skill describes what *this skill* does, its inputs, its outputs, and its internal
decision rules. It does not describe who calls it, when it is dispatched, what happens to
its outputs, or how failures are routed. Any sentence mentioning DAG structure, stage
relationships, or dispatch mechanics is a violation.

### Dispatcher exemption

Two kinds of skill carry orchestration vocabulary in-role, so it is their subject matter
rather than a violation:

1. **Router** — `design-flow`. Its output *is* a routing decision; DAG / orchestrator /
   routing vocabulary is what the skill is about.
2. **Fan-out dispatchers** — `specification`, `rtl-design`, `simulation`, and
   `simulation-plan`. These are main-thread skills that hold Level-1 sub-Task dispatch
   authority. `specification` runs two sub-Task waves around its partition gate,
   `rtl-design` runs one per-child fan-out wave, `simulation` runs two sequential waves
   around its smoke gate, and `simulation-plan` self-dispatches a single Level-1
   plan-adequacy review sub-Task at its adequacy gate. Because dispatching and reaping
   their own Level-1 sub-Tasks *is* their control flow, `dispatcher` / `orchestrate` /
   `sub-Task` / `wave` / `Task` vocabulary in their `SKILL.md` describes the skill's own
   operation, not a sibling stage or the DAG.

**Decision criterion:** the vocabulary describes *this skill's own operation* — emitting a
routing decision (router) or driving its own intra-stage fan-out (fan-out dispatcher) →
exempt. The vocabulary describes who calls the skill, what happens to its outputs, or how
its failures are routed → working-stage narrative → scrub rule applies, even inside a
fan-out dispatcher.

The exempt set is closed: `design-flow` + the four fan-out dispatchers above. A new
dispatcher must be explicitly named here before the exemption applies to it.

## 2. References organization

### Background

VeriPower uses a three-layer content model:

1. **SKILL.md body** — entry point; inline-friendly content the agent reads in a single
   context load.
2. **`skills/<name>/references/`** — skill-private externalizations; specific to one stage.
3. **`framework/references/`** — cross-skill shared pool; centralized to prevent N-copy
   drift.

Each layer has a distinct purpose; blurring the boundary creates duplicate anchors for the
same rule. *N copies = N drift anchors.*

### Principles

**P1 — Single canonical home.** Every rule has exactly one canonical home; cross-references
use markdown links, never duplication. The same principle applies to field-level content —
see `skill-field-contract-design.md` for the field-placement application.

**P2 — Hard criteria plus soft signals.** Externalize when a hard criterion is met.
Soft signals (concept orthogonality, evolution cadence difference) are reviewer hints only —
authors do not externalize on soft signals alone.

**P3 — One-layer `references/`.** `references/` is a flat directory: no nested
subdirectories. Private references (`skills/<name>/references/`) must not cross-reference
other skills' private references; only `framework/references/` is shareable across skills.

**P4 — Filename default.** Markdown files use kebab-case; Python files follow PEP 8
snake_case. Suffixes (e.g. `*.schema.json`, `*-rules.md`, `*-template.md`) follow the
suffix taxonomy in the externalization decision cascade below; use the first matching type.

### Externalization decision cascade

Apply steps in order; stop at the first match.

1. **Hard criteria (any one match → externalize):**
   - Machine contract: program-consumed structured data (e.g., `result.schema.json`,
     `envelope.schema.json`).
   - Cross-skill shared: consumers in different skills; not externalizing forces N drift
     copies.
   - Fits a recognized suffix type AND is ≥ 30 lines (self-contained; readable without
     surrounding SKILL.md context).

2. **Soft signals (reviewer hint only — not a mandate):**
   - Concept orthogonal to the surrounding workflow context.
   - Evolution cadence differs from the skill body.
   - Length smell: SKILL.md body > 250 lines — signal to re-examine, not a mandate.

3. **Default: keep inline.**

### Always-inline content

The following are always kept in the SKILL.md body. All are stage-bound; externalizing adds
navigation cost without separability benefit.

- **Workflow** — the agent reads steps in sequence during execution; external loading breaks
  single-context.
- **Pitfalls** — mid-flow warnings needed in context during Workflow execution.
- **Completion Gate** — pre-return checklist; co-located with Return Contract.
- **Return Contract** — terminal action; inseparable from Completion Gate.
- **Decision Rules** — local priority-conflict rules scoped within this stage.
- **When to Use** — the dispatcher reads this at invocation time.
- **Iron Rule** — architectural boundary constraints; must be visible before step 1.
- **Input/Output Artifacts tables** — stage-specific I/O; orphans if externalized.

### Cross-skill reference syntax

Reference other skills by name with the `veripower:` namespace prefix. Never use `@`-path
includes or file-path cross-links that force-load another skill's context.

**Good:** *"For verification-plan authoring, see veripower:simulation-plan."*

**Bad:** *"For verification-plan authoring, see `@skills/simulation-plan/SKILL.md`."*

**Bad:** *"Read `skills/simulation-plan/SKILL.md` first, then return here."*
(sequence dependency)

Markdown links within a doc are fine — they are navigation aids that do not force-load
context.
