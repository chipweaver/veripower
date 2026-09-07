---
name: brainstorm
description: Use when brainstorming a new module's requirements and architecture into a brainstorm.md, one way to write the intent document the pipeline starts from; not for design.md, RTL, constraints, or any in-pipeline stage.
---

# Pre-Pipeline Requirements Brainstorm

Run an interactive dialogue with the engineer and write `{module}/intent/brainstorm.md`, one
way to produce the intent document the pipeline starts from. You run **in your own session,
before the pipeline** — this conversation never enters the pipeline's context.

Write that one file and nothing else: no `result.json`, no `design.md`, no RTL, no
constraints. You are not a pipeline stage and no pipeline state exists yet. The document is
frozen once a run starts, so a requirements change is a fresh invocation of this skill, never
an edit to an in-flight artifact.

Re-invoked after a downstream contradiction was escalated, the existing document is your
input: what is left to ask is what the change unsettles, and you say in the document which
parts this round did not touch.

## Where the output goes

`{module}` is wherever the engineer wants — `~/chips/mydesign`, `./mychip`, `asic/mychip` —
and is the same path the pipeline is later given as `--module`; its last component is the
module name. If they named only a module, ask for the directory. Do not invent a parent:
nothing downstream imposes one, and a guess sends them looking for a tree they did not ask for.

Create `{module}/intent/` if absent. That directory is the whole of what the pipeline treats
as intent, so anything the engineer delivers with the document — a reference model, a register
map, a standard the document names as authoritative — belongs inside it. A file left at the
module root is not intent: no stage is handed it and no proof records it.

## The dialogue

Settle intent and scope first, and do not enter the rest until it is clear. After that, what
is left to ask is whatever the material the engineer brought does not already settle — someone
arriving with a protocol standard and a register map has settled their interfaces and clocking
in the document they brought, and asking again spends the only thing this dialogue costs. Read
the material first.

The dialogue is done when none of these is still unspoken for: intent and scope · functions
and features · top-level IO, and inter-module wires when N>1 · clocks, resets, and every
crossing between them · architecture partition · timing scenarios · PPA targets · readiness.
What each one contains you can work out; whether *this* project has settled it, you cannot.

One question at a time, and end each with the answer you would give and why — a question with
no recommendation makes the user do your work. Where the partition is still open, put 2-3
candidates side by side so they choose rather than inherit your first idea; where the input
already fixes it, say so in a line. When a question wants a diagram, the conventions are in
`skills/specification/references/design-template.md` §Rendering Conventions.

On readiness, ask whether the stages that author from this document could do so without coming
back. Their own references say what they need, field by field — read them there. A list kept
here would be a copy that goes stale while nothing checks it. Name every gap you find, by name.

## Four things this dialogue is the last chance to settle

- **A number a reference implementation would answer** — a latency, a byte width, a
  state-machine cycle count. Settle it here with its source. Deferred, it reaches design.md as
  a wrong first draft and a run of Edits on the main thread.
- **Reset polarity, and sync vs async** — deferred, it becomes an SDC-stage guess.
- **What is deliberately left unconstrained** — a PPA dimension with no bound, a behaviour
  left to the implementer, a bound some outside authority owns. Say so, and say which:
  `specification` writes a row for each of those too and the ledger tells them apart by
  `judge`. What it cannot do is tell a deliberate silence from a forgotten one.
- **Every open question** — a question is not a proposition, so it gets no ledger row, and the
  document is frozen for the run: a TBD settled later is settled somewhere else.

## The document, and handing it off

Write what the engineer would recognize as their own document, one statement per proposition:
`specification` reads it whole, top to bottom, and transcribes one ledger row per atomic
proposition in the engineer's words, so a sentence carrying three of them makes that split a
guess. Nothing reads a heading and no shape is a contract — when the engineer brought a
document, keep theirs. Descriptive headers and stable names help whoever reads it next.

Before handing off, re-read what you just wrote and fix inline any defect that would survive
the freeze: an unsettled placeholder, a contradiction between two parts of the document (a
clock named in an interface table but absent from the clock list), or a two-way-ambiguous
requirement.

Then give the user the on-disk path and a short orientation — the areas covered, and on a
revision, which ones changed. **Do not echo the document body.** Then stop: the user reads it,
and starting the pipeline with `--module {module}` is how they say it is right. Nothing is
dispatchable until that file exists.
