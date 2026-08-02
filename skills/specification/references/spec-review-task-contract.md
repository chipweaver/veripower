# Spec semantic review sub-Task contract

The specification main thread dispatches one Level-1 reviewer per child as its third wave, AFTER
`check-crossrefs` is green and BEFORE the design.md approval gate. You write your findings to a
file; the main thread never re-types them and never reads your body. A human resolves each
blocker at that gate. Do not call the Task tool: a sub-Task writes no events, so anything you
dispatch is work the kernel cannot see or audit.

## Per-child reviewer (one per `manifest.children[]`)

### Inputs (paths only)
- The child's per-child design doc, located via `manifest.children[<self>].doc`.
- `<brainstorm>/brainstorm.md`, **read all of it** — the frozen statement of *intent*. Your
  child's `brainstorm_anchor` says which passage is primarily yours: start there, but a formula
  or constraint stated anywhere in the document is in scope. (Slices do not cover the document —
  on a real module 53% of the lines fell in no child's anchor — and slicing would presume a shape
  a human-authored dialogue does not owe us.)
- `design.md`, read-scope §1.4 only (top IO / interconnects, **including the §1.4.x Encoding
  field and the §1.4.2.1 Inter-module Behavior Contract companion when present**) — integration
  context, and the frame for anything encoding-related.

### Your job: skeptical intent review of the SPEC (NOT RTL / lint / PPA)
You are a fresh reviewer. **Do not trust that the spec is correct because it is written.** Read
the `<child>.md` against the brainstorm intent and against `design.md` §1.4, and report what is
wrong with it.

What is worth reporting, in descending order of what it costs to find later:

- The doc omits, contradicts, or silently adds to something the brainstorm requires.
- A **control/status** §1.4.x row this child consumes or drives pins an Encoding too thin for the
  consumer to implement its decode with no guessing — or this child's §2/§3 decode contradicts
  the row it claims to follow.
- Two or more `interconnects.json` wires reference the same named phase / sequence that the
  §1.4.2.1 companion never declares (including: such references exist and there is no companion).
- The micro-architecture this child introduces cannot realize the behavior it promises, or two
  interfaces disagree in a way no single frame settles.

Out of scope: RTL correctness (no RTL exists yet); lint / CDC / timing / area / power; and the
deterministic checks the scripts own (sidecar shapes, top-partition purity, cross-file name
resolution, every top output claimed). If you happen to see one of those, say so — but
as an observation, not as your finding.

### Output: `{workdir}/spec-review/<child>.md`

Write the file yourself. Free prose, one section per finding, in whatever order serves the
reader. Each finding states three things:

- **What you compared against** — the brainstorm, a named `design.md` §1.4.x row, or nothing
  (your own judgment). This is the single most useful thing you can tell the human: a finding
  with a frame can be re-checked by anyone; one without it is your opinion, and is resolved as
  such.
- **Blocks or not** — would shipping this spec downstream as-is be a defect? Say it plainly.
  A finding you cannot check against anything goes to the human as something to weigh.
- **Where and what** — the `<child>.md` section, and one line on what is wrong.

Then end your turn with `STATUS: DONE` and the path you wrote, or `STATUS: BLOCKED <reason>`
if a program exception stopped you from writing it.
