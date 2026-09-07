# IC Spec Brainstorm Checklist

## What is left to ask

Whatever the delivered material does not already settle. An engineer arriving with a protocol
standard and a register map has settled their interfaces and clocking in the document they
brought; asking again spends the only thing this dialogue costs. Read the material first.

Two things do not scale with the module: **D0 is asked first** (do not enter the rest until
intent is clarified), and the user approves what lands on disk. Everything else does.

## Coverage

The dialogue is done when none of these is still unspoken for. What each one contains you can
work out; whether *this* project has settled it, you cannot.

**D0** intent and scope · **D1** functions and features · **D2** top-level IO, and inter-module
wires when N>1 · **D3** clocks, resets, and every crossing between them · **D4** architecture
partition · **D5** timing scenarios · **D6** PPA targets · **D7** readiness

One question at a time, and end each with the answer you would give and why — a question with no
recommendation makes the user do your work. Where D4's partition is still open, put 2-3 candidates
side by side so they choose rather than inherit your first idea; where the input already fixes it,
say so in a line. Diagram conventions, when a question wants one:
`../../specification/references/design-template.md` §Rendering Conventions.

## Four things this dialogue is the last chance to settle

- **A number a reference implementation would answer** — a latency, a byte width, a state-machine
  cycle count. Settle it here with its source. Deferred, it reaches design.md as a wrong first
  draft and a run of Edits on the main thread.
- **Reset polarity, and sync vs async** — deferred, it becomes an SDC-stage guess.
- **A PPA dimension you deliberately leave unbounded** — say so. The ledger distinguishes "asked,
  bounded by nothing" from "never asked"; silence reads as the second.
- **Every open question** — a question is not a proposition, so it gets no ledger row, and the
  document is frozen for the run: a TBD settled later is settled somewhere else.

## Readiness

Ask whether the stages that author from this document could do so without coming back. Their own
references say what they need, field by field — read them there. A list kept here would be a copy
that goes stale while nothing checks it. Name every gap you find, by name.

## The written document

Descriptive headers, one per dimension reached; `Dx` is a dialogue label and never appears in the
artifact. This shape is **this skill's default, not a contract** — specification transcribes the
document into one ledger row per proposition, so no stage reads a heading, and every intent
document delivered to this pipeline so far arrived in a shape of its own. When the engineer
brought a document, keep theirs. Stable names help whoever reads it next; nothing parses them.

Revision mode re-reads the existing document, which makes it the delivered material: what is left
to ask is what the change unsettles. Note in the document which dimensions this round did not
touch.
