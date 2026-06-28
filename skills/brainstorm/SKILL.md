---
name: brainstorm
description: Use when brainstorming a new module's requirements and architecture to produce an approved brainstorm.md before the pipeline; not for design.md, RTL, constraints, or any in-pipeline stage.
---

# Pre-Pipeline Requirements Brainstorm

Own the interactive D0–D7 brainstorm dialogue and produce a frozen
`asic/{module}/brainstorm.md`. Run **in your own session, before** the design
pipeline: the brainstorm conversation never enters the pipeline's context. The pipeline
starts only after `brainstorm.md` reaches `Status: approved`, and reads that file solely
inside its sub-agent contexts (it is the pipeline's input, not a pipeline stage).

## When to Use

- A new module needs its requirements + architecture settled before the pipeline.
- A requirements contradiction surfaced downstream and was escalated for revision: the
  user aborts, re-invokes this skill in revision mode, re-approves.

## Iron Rule

- You are **pre-pipeline**: write exactly one artifact, `asic/{module}/brainstorm.md`
  (creating `asic/{module}/` if absent, before the module enters the pipeline). Write
  **no** `result.json`, and you are **not** a pipeline stage — you run before any pipeline state exists.
- **Do not author design.md / RTL / constraints / any downstream artifact.** Your
  output is the brainstorm only; `design.md` is derived from it downstream.
- `brainstorm.md` is **immutable once approved** for the duration of a run. A requirements
  change is handled by re-invoking this skill in revision mode and re-approving — never
  edit an in-flight artifact to absorb a change.

## Input Artifacts

| Variable / input | Purpose |
|---|---|
| `{module}` | Module name (used for the `asic/{module}/` path + the brainstorm title). |
| User-provided material (optional) | Public spec / reference docs the user pastes or points to. |

No fixed external inputs. Revision mode additionally reads the existing
`asic/{module}/brainstorm.md`.

## Output Artifacts

| Path | Schema / Format | Use |
|---|---|---|
| `asic/{module}/brainstorm.md` | Custom markdown; frontmatter `Status: draft\|approved`; descriptive ATX sections per the checklist's Section Layout | The pipeline's frozen input. |

`brainstorm.md` lives at the **module root**, NOT under any stage workdir. There
is **no** `version` frontmatter field (re-derivation after a revision is given naturally
by the fresh run's empty workdir).

## Workflow

### Step 1: Read `{module}` + any user-provided material

### Step 2: D0–D7 dimensional brainstorm dialogue

(one question at a time, multiple-choice
preferred; D0 first; D4 presents 2–3 candidate architectures with side-by-side
mermaid): see `references/brainstorm-checklist.md`.

### Step 3: Write `asic/{module}/brainstorm.md`

with descriptive section headers per the
checklist's Section Layout (create `asic/{module}/` if it does not exist), with
frontmatter:
```markdown
---
Status: draft
---

# <module> Brainstorm
...
```

### Step 4: Approval gate (path-handoff)

First re-read the just-written `brainstorm.md` and
fix inline any defect that would survive the freeze: a placeholder / unsettled `OQ-NN`,
a cross-dimension contradiction (e.g. a clock in a D2a clock-domain column but absent
from the D3 clock list), or a two-way-ambiguous requirement. Then point the user to the
on-disk path + a short orientation (the D-dimensions covered; revision mode: only the D
sections changed this round). **Do not echo the brainstorm body** (sections / tables /
mermaid / code). On explicit user agreement, set frontmatter `Status: approved`. While
`Status: draft`, do not hand off to the pipeline.

### Step 5: Revision mode

(re-invoked after an abort): re-ask only the affected D dimensions,
preserve the rest, then re-run the Step 4 approval gate (its self-review re-reads the
whole doc, so a changed dimension contradicting an untouched one is caught).

## Red Flags

| Excuse | Reality |
|---|---|
| "The requirements changed — I'll just edit the approved brainstorm to absorb it" | Absorb a requirements change by re-invoking in revision mode + re-approving — never by editing an in-flight artifact (Iron Rule: `brainstorm.md` is immutable once approved). |

## Completion Gate

- `asic/{module}/brainstorm.md` exists with frontmatter `Status: approved`.
- The brainstorm covers the D0–D7 dimensions reached (D0 intent settled; D4 had 2–3
  candidates; feature IDs / interface-group names / scenario IDs are stable named
  anchors per the checklist's "Subsection IDs" section).
- The brainstorm body was **not** echoed into the conversation (path-handoff only).
- No `result.json` / pipeline-state command issued (Iron Rule — pre-pipeline).

## Return Contract

Control returns to the user. Produce only `asic/{module}/brainstorm.md` (no `result.json`, no state files — per the Iron Rule). After approval, the user starts
the pipeline for `{module}`; its entry gate verifies the approved brainstorm before the
first stage consumes it.

## Bundled References

- [`references/brainstorm-checklist.md`](references/brainstorm-checklist.md) — D0–D7 dimensional Q&A checklist + style + trimming rules + diagram conventions.
