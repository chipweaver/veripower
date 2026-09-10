# skill-structure-design.md — skill containment + references organization

## 1. Self-containment

### Background

VeriPower's DAG topology is derived from `rules.py`'s artifact selectors and every routing
decision is computed by `schedule.decide`; `design-flow` is the thin executor that runs the
one action `decide` returns. Its subject matter is executing the routing decision.
Individual stage skills, in contrast, describe a bounded operation: what they receive, what
they produce, and what they decide internally. They do not describe DAG position or who calls
them. DAG-agnostic descriptions stay composable and replaceable — topology can evolve without
touching stage content.

**A failing stage names its own `fix_owner`.** It reports what it found in the raw tool
output; the symptom's location does not necessarily identify the artifact to fix. A stage still decides
nothing about scheduling: it names a rule, and `schedule.py` checks that naming against the
derived input closure before anything is dispatched.

### Principle — describe self, not orchestration

A stage skill describes what *this skill* does, its inputs, its outputs, and its internal
decision rules. Keep orchestration detail where it is needed to execute the task.

### Dispatching skills

Two kinds of skill describe dispatch as part of their work:

1. **Router** — `design-flow`. What it executes *is* a routing decision; DAG / orchestrator /
   routing vocabulary is what the skill is about.
2. **Fan-out dispatchers** — `specification`, `rtl-design`, `simulation`, and
   `simulation-plan`. These are main-thread skills that hold Level-1 sub-Task dispatch
   authority: each dispatches its authoring and reviewing children around its own gates.

## 2. References organization

### Background

VeriPower uses a three-layer content model:

1. **SKILL.md body** — entry point; inline-friendly content the agent reads in a single
   context load.
2. **`skills/<name>/references/`** — skill-private externalizations; specific to one stage.
3. **`framework/references/`** — cross-skill shared references.

Each layer serves a different set of readers.

### Principles

**P1 — Single canonical home.** Every rule has exactly one canonical home; cross-references
use markdown links, never duplication. Applied to a rule's own placement, the home is whichever
artifact a reader will consult anyway: the schema description for a field, the `--help` for a
flag, the corpus of SKILL.md for an authoring convention.

**P2 — Reader need.** Externalize a topic when readers benefit from consulting it separately.

**P3 — One-layer `references/`.** `references/` is a flat directory: no nested
subdirectories. Private references (`skills/<name>/references/`) must not cross-reference
other skills' private references; only `framework/references/` is shareable across skills.

**P4 — Filename default.** Markdown files use kebab-case; Python files follow PEP 8
snake_case. Use descriptive suffixes such as `*.schema.json`, `*-rules.md` and `*-template.md`.

### When to externalize

Consider the consumers and the topic's independence.

1. **Reasons to externalize:**
   - Machine contract: program-consumed structured data (e.g., `result.schema.json`,
     `envelope.schema.json`).
   - Cross-skill shared: consumers in different skills.
   - A self-contained topic that is readable without surrounding SKILL.md context.

2. **Other considerations:**
   - Concept orthogonal to the surrounding workflow context.
   - Evolution cadence differs from the skill body.

3. **Default: keep inline.**

### SKILL.md entry-point content

The SKILL.md body introduces the task and links to detail where it is used.

- **Iron Rule** — architectural boundary constraints; must be visible before step 1.
- **Artifacts** — one section, split by who writes each file, not by in/out. Stage-specific.
- **Workflow** — the execution sequence, with links to task references.
- **Return Contract** — the terminal action.

### Cross-skill reference syntax

Reference other skills by name with the `veripower:` namespace prefix. Never use `@`-path
includes or file-path cross-links that force-load another skill's context.

**Good:** *"For verification-plan authoring, see veripower:simulation-plan."*

**Bad:** *"For verification-plan authoring, see `@skills/simulation-plan/SKILL.md`."*

**Bad:** *"Read `skills/simulation-plan/SKILL.md` first, then return here."*
(sequence dependency)

Markdown links within a doc are fine — they are navigation aids that do not force-load
context.
