# Per-child intent review sub-Task contract

The rtl-design main thread dispatches one Level-1 `Task(run_in_background=True)` per child in
`manifest.children[]`, on every round that reaches a written sidecar. You write your own review
file. Nothing reduces it to a verdict: it is promoted as this stage's proposed oracle, and a human
`pin` is what converts it into signoff-grade trust. So write for the engineer who will read it
before signing, not for a parser. Do not call the Task tool.

## Inputs (paths only — the main thread does not read these bodies)

- Child unit name + its `manifest.children[<self>].rtl_modules[]` list.
- The child's authored RTL `files[]` (from `rtl-files.json`) — read these.
- The child's per-child design doc, located via `manifest.children[<self>].doc` (the registry SSoT —
  the SAME path authoring uses; do NOT hardcode `Design/specification/<child>.md`, which can drift from
  the deployed layout). **Read its §2 Interface (and, for the top-integration child, the §3.1
  instantiation map wires the `interconnects.json` edges)** as the statement of *intent* to check against.
- `design.md` path, read-scope §1.4 only, for cross-checking integration **intent** (including §1.4.2.1's
  inter-module behavior contract). No deterministic gate matches the edge list against the RTL any
  more, so a module or wire the spec names and the RTL does not (or renames) is yours to catch —
  report it as `missing`.

## Your job: skeptical intent review (NOT lint / PPA / syntax)

You are a fresh reviewer. **Do not trust that the RTL is correct because it exists.** Read the
actual RTL and compare it against the `<child>.md §2` intent, in both directions: what §2 requires
and the RTL lacks, and what the RTL does that §2 never asked for.

Three things are worth flagging, and the third differently from the first two:

- **Missing / under-built** — behavior §2 requires that the RTL does not implement.
- **Wrong behavior** — RTL that compiles and reads plausibly but does not do what §2 says. An
  arbiter spec'd round-robin and built fixed-priority is the shape to look for.
- **Over-engineering** — logic, state or ports beyond what §2 asks for. This one is worth
  recording and rarely worth blocking: unrequested configurability at a correct default costs
  area, not correctness.

Attributing a defect to the spec is the consequential call, so make it deliberately. An interface
width that cannot hold the value §2 requires is the spec's, and hard evidence. RTL that merely
does the wrong thing is this child's, even when §2 could have been clearer. Say which, and say
how sure you are — the stage routes a spec rebuild on your reading alone, with no triage step
behind it, so an uncertain attribution should read as uncertain.

**Out of scope (do NOT report):** synthesizability / timing / area / power (downstream stages);
lint / CDC rule violations (lint-cdc); pure syntax and whole-design elaboration (the child
self-checks, and lint-cdc elaborates).

## Output

Write `{workdir}/semantic-review/<your-child>.md`. Prose, no schema. Then end the response with
`STATUS: DONE`, or `STATUS: BLOCKED <reason>` if you could not review at all.

Every finding says four things:

- **Where** — the file and line, or the `<child>.md §2` clause it violates.
- **What you compared against** — the §2 clause, the §1.4 integration intent, or nothing (then say
  so: an unreferenced finding is your opinion, and it is read as one).
- **Whether it blocks** — would you let this ship? Say so plainly. Calibrate: reserve blocking for
  behaviour downstream will not catch cheaply.
- **Where the fix belongs** — this child's RTL, or the spec itself. A width that cannot hold the
  value §2 requires is the spec's; RTL that just does the wrong thing is the child's. Say which,
  and how sure you are, because the stage routes an upstream repair on your reading alone.

Write nothing when you found nothing — an empty findings section with a sentence saying you read
§2 against the RTL and it holds. A file that does not exist reads as a review that never ran, and
the stage cannot pass without yours.
