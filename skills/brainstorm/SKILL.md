---
name: brainstorm
description: Use when brainstorming a new module's requirements and architecture into a brainstorm.md, one way to write the intent document the pipeline starts from; not for design.md, RTL, constraints, or any in-pipeline stage.
---

# Pre-Pipeline Requirements Brainstorm

Own the interactive D0–D7 brainstorm dialogue and produce a frozen
`{module}/intent/brainstorm.md`. Run **in your own session, before** the design
pipeline: the brainstorm conversation never enters the pipeline's context. The pipeline
starts when the user starts it and reads that file solely inside its sub-agent contexts
(it is the pipeline's input, not a pipeline stage).

## When to Use

- A new module needs its requirements + architecture settled before the pipeline.
- A requirements contradiction surfaced downstream and was escalated for revision: the
  user aborts, re-invokes this skill in revision mode, re-approves.

## Iron Rule

- You are **pre-pipeline**: write exactly one artifact, `{module}/intent/brainstorm.md`
  (creating `{module}/intent/` if absent, before the module enters the pipeline). Write
  **no** `result.json`, and you are **not** a pipeline stage — you run before any pipeline state exists.
- **Do not author design.md / RTL / constraints / any downstream artifact.** Your
  output is the brainstorm only; `design.md` is derived from it downstream.
- `brainstorm.md` is **frozen for the duration of a run**. A requirements change is handled
  by re-invoking this skill in revision mode, never by editing an in-flight artifact to
  absorb the change: every proof downstream records the fingerprint it read.

## Input Artifacts

| Variable / input | Purpose |
|---|---|
| `{module}` | The module's directory — the same path the pipeline is later given as `--module`, and where its whole work tree goes. Anywhere the user wants: `~/chips/mydesign`, `./mychip`, `asic/mychip`. Its last component is the module name, which titles the brainstorm. |
| User-provided material (optional) | Public spec / reference docs the user pastes or points to. |

No fixed external inputs. Revision mode additionally reads the existing
`{module}/intent/brainstorm.md`.

Ask for the directory if the user named only a module. Do not invent a parent for them:
nothing downstream imposes one, and a guess sends them looking for a tree they did not ask for.

## Output Artifacts

| Path | Schema / Format | Use |
|---|---|---|
| `{module}/intent/brainstorm.md` | Custom markdown; descriptive ATX sections per the checklist's Section Layout | The pipeline's frozen input. The pipeline assumes nothing about its shape: an engineer's own document in any form serves the same, and this skill is one way to write one. |

`brainstorm.md` lives in `{module}/intent/`, the intent container, NOT under any stage
workdir. That directory is the whole of what the pipeline treats as intent: anything the
engineer delivers with the document — a reference model, a register map, a standard the
document names as authoritative — belongs in it, and one fingerprint over the directory is
what every downstream proof records. A file left at the module root instead is not intent;
no stage is handed it and no proof records it. There is **no** `version` frontmatter field
(re-derivation after a revision is given naturally by the fresh run's empty workdir).

## Workflow

### Step 1: Settle `{module}` + read any user-provided material

### Step 2: D0–D7 dimensional brainstorm dialogue

(one question at a time, multiple-choice
preferred; D0 first; D4 presents 2–3 candidate architectures with side-by-side
mermaid): see `references/brainstorm-checklist.md`.

### Step 3: Write `{module}/intent/brainstorm.md`

with descriptive section headers per the
checklist's Section Layout (create `{module}/intent/` if it does not exist):
```markdown
# <module> Brainstorm
...
```

### Step 4: Hand off the path

First re-read the just-written `brainstorm.md` and
fix inline any defect that would survive the freeze: a placeholder / unsettled `OQ-NN`,
a cross-dimension contradiction (e.g. a clock in a D2a clock-domain column but absent
from the D3 clock list), or a two-way-ambiguous requirement. Then point the user to the
on-disk path + a short orientation (the D-dimensions covered; revision mode: only the D
sections changed this round). **Do not echo the brainstorm body** (sections / tables /
mermaid / code). Then stop: the user reads it, and starting the pipeline is how they say
it is right.

### Step 5: Revision mode

(re-invoked after an abort): re-ask only the affected D dimensions,
preserve the rest, then re-run Step 4 (its self-review re-reads the
whole doc, so a changed dimension contradicting an untouched one is caught).

## Completion Gate

- `{module}/intent/brainstorm.md` exists, and any file the document names as authoritative sits beside it in `{module}/intent/`.
- The brainstorm covers the D0–D7 dimensions reached (D0 intent settled; D4 had 2–3
  candidates; feature IDs / interface-group names / scenario IDs are stable named
  anchors per the checklist's "Subsection IDs" section).

## Return Contract

Control returns to the user. The user starts the pipeline with `--module {module}`
when they are satisfied with what is on disk; the kernel will not dispatch `specification`
until that file exists.

## Bundled References

- [`references/brainstorm-checklist.md`](references/brainstorm-checklist.md) — D0–D7 dimensional Q&A checklist + style + trimming rules + diagram conventions.
