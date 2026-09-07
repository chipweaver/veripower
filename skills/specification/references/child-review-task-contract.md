# Child design review sub-Task contract

The specification main thread dispatches one Level-1 reviewer per child AFTER
`check-crossrefs` is green and BEFORE the design gate. You write your findings to a
file; the main thread never re-types them and never reads your body. A human resolves each
blocker at that gate. Do not call the Task tool: a sub-Task writes no events, so anything you
dispatch is work the kernel cannot see or audit.

## Per-child reviewer (one per `manifest.children[]`)

### Inputs (paths only)
- The child's per-child design doc, located via `manifest.children[<self>].doc`, and its
  `check-hints/<child>.json`.
- `requirements.json`, **read all of it** — the engineer's requirements, one row each with the
  judge that establishes it. The rows your child realizes are not marked; you recognize them.
- `design.md` — the integration decisions the child sits inside: the wiring, the inter-module
  behaviour contract siblings must jointly keep, the timing scenarios.

### Your job: skeptical review of the child design against the requirements (NOT RTL / lint / PPA)
You are a fresh reviewer. **Do not trust that the design is correct because it is written.** Read
the `<child>.md` and its hints against the requirement rows and against `design.md`, and report
what is wrong with them.

What is worth reporting, in descending order of what it costs to find later:

- The doc omits, contradicts, silently adds to, or restates instead of citing a requirement row.
- A hint observes an internal signal without the child design saying why the boundary does not
  suffice, or a hint's rule cannot establish the rows it names.
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

- **What you compared against** — a requirement row id, a `design.md` decision, or nothing (your
  own judgment). This is the single most useful thing you can tell the human: a finding
  with a frame can be re-checked by anyone; one without it is your opinion, and is resolved as
  such.
- **Blocks or not** — would shipping this spec downstream as-is be a defect? Say it plainly.
  A finding you cannot check against anything goes to the human as something to weigh.
- **Where and what** — the `<child>.md` section, and one line on what is wrong.

Then end your turn with `STATUS: DONE` and the path you wrote, or `STATUS: BLOCKED <reason>`
if a program exception stopped you from writing it.
