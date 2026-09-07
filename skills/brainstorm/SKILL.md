---
name: brainstorm
description: Use when brainstorming a new module's requirements and architecture into a brainstorm.md, one way to write the intent document the pipeline starts from; not for design.md, RTL, constraints, or any in-pipeline stage.
---

# Pre-Pipeline Requirements Brainstorm

Interview the engineer and write `{module}/intent/brainstorm.md`, one way to produce the intent
document the pipeline starts from. Run **in your own session, before the pipeline** — this
conversation never enters the pipeline's context, and you write no `result.json`.

The document is frozen once a run starts, so a requirements change is a fresh invocation of
this skill, never an edit to an in-flight artifact. Re-invoked that way, the existing document
is your input: what is left to ask is what the change unsettles, and you say in the document
which parts this round did not touch.

## Where the output goes

`{module}` is any path the engineer wants — the same one the pipeline is later given as
`--module`. If they named only a module, ask; do not invent a parent, or you send them looking
for a tree they did not ask for.

Create `{module}/intent/` and put the document in it, along with anything the engineer delivers
that it names as authoritative — a reference model, a register map, a standard. That directory
is the whole of what the pipeline treats as intent: a file left at the module root is handed to
no stage and recorded by no proof.

## The dialogue

What is left to ask is whatever the material the engineer brought does not already settle.
Someone arriving with a protocol standard and a register map has settled their interfaces and
clocking; asking again spends the only thing this dialogue costs.

It is done when none of these is still unspoken for: intent and scope · functions and features
· top-level IO, and inter-module wires when N>1 · clocks, resets, and every crossing between
them · architecture partition · timing scenarios · PPA targets · readiness. What each one
contains you can work out; whether *this* project has settled it, you cannot.

One question at a time, and end each with the answer you would give and why — a question with
no recommendation makes the user do your work. Where the partition is still open, put 2-3
candidates side by side so they choose rather than inherit your first idea.

On readiness, ask whether the stages that author from this document could do so without coming
back, and name every gap you find.

## Four things this dialogue is the last chance to settle

- **A number a reference implementation would answer** — a latency, a byte width, a
  state-machine cycle count. Settle it here with its source. Deferred, it reaches design.md as
  a wrong first draft and a run of Edits on the main thread.
- **Reset polarity, and sync vs async** — deferred, it becomes an SDC-stage guess.
- **What is deliberately left unconstrained** — a PPA dimension with no bound, a behaviour left
  to the implementer, a bound some outside authority owns. Say which: the ledger has a `judge`
  for each of those, and none for a silence it cannot read.
- **Every open question** — a question is not a proposition, so it gets no ledger row, and the
  document is frozen: a TBD settled later is settled somewhere else.

## The document, and handing it off

Keep the engineer's own document when they brought one. `specification` transcribes it whole,
one ledger row per atomic proposition in their words, and reads no heading — so what you owe is
one proposition per statement, not a layout.

Re-read what you wrote and fix inline anything that would survive the freeze: a placeholder, a
two-way-ambiguous requirement, a contradiction between two parts of the document, or between
the document and a file it cites as authoritative.

Then hand over the path and a short orientation — the areas covered, and on a revision, which
ones changed. **Do not echo the document body.** Then stop: nothing is dispatchable until that
file exists, and starting the pipeline is how the engineer says it is right.
