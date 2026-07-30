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
actual RTL line by line and compare it against the `<child>.md §2` intent. Check **both directions**:

- **Missing / under-built:** behavior the `<child>.md §2` requires that the RTL does not implement.
- **Wrong behavior (plausible-but-wrong):** RTL that compiles and looks reasonable but does NOT do
  what §2 specifies (e.g. an arbiter spec'd round-robin but implemented fixed-priority).
- **Over-engineering (YAGNI):** logic / state / ports beyond what §2 intent calls for.

**For every finding, assign `fix_locus`** — where the fix must land (it tags the gate's `fail_reason`
so the operator knows where to fix, and routes future automation):
- `fix_locus: "rtl"` — the fix is in *this child's RTL* (the implementation deviates from, or under-builds,
  the `<child>.md §2` intent; `over-engineering` is always `rtl`).
- `fix_locus: "spec"` — the defect is a contradiction or omission in `design.md` / the `<child>.md` spec
  itself, which this child cannot fix from RTL (e.g. an interface width that cannot hold the value §2
  requires). Do not flag `spec` for something the RTL alone can fix.

- **`confidence`, on every `fix_locus: "spec"` finding** (omit it elsewhere): how sure you are of the
  attribution that this really is a `design.md` / `<child>.md` intent defect needing an upstream fix.
  `high` = the interface or intent contradiction is hard evidence (a width that cannot hold the value §2
  requires); `medium` / `low` = the RTL side might still be able to salvage it. rtl-design has no triage
  re-check, so this is the only trust signal the upstream route gets: when unsure give `low` and let the
  kernel escalate to a human, rather than betting a spec rebuild on it. An omitted `confidence` is read as
  `low` for exactly that reason, so leaving it out never buys a stronger route.

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
