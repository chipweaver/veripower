# Per-child semantic review sub-Task contract (gating)

The rtl-design main thread dispatches one Level-1 `Task(run_in_background=True)` per child
in `manifest.children[]` **on every finalize that reaches a clean gate** (not first-run only),
AFTER `assemble` has written the sidecars. This review is **gating**: findings
in `category ∈ {missing, wrong-behavior}` at `severity ∈ {critical, important}` trip a gate that
fails the stage out (`status=fail`) to the operator. `over-engineering` and `minor` findings
remain advisory (never gate). Findings are aggregated into `semantic-review.json`. Do not call the Task tool.

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

End the response with `STATUS: DONE` + a single JSON line, or `STATUS: BLOCKED <reason>`:

```json
{"child": "<name>",
 "findings": [{"severity": "critical|important|minor",
               "category": "missing|wrong-behavior|over-engineering",
               "fix_locus": "rtl|spec",
               "confidence": "high|medium|low",
               "location": "<file:line or <child>.md §2 ref>", "summary": "<one line>"}]}
```

- **severity guidance:** `critical` = likely wrong functionality that downstream may not catch cheaply;
  `important` = real concern worth a look; `minor` = nit. Calibrate — not everything is critical.
- **`fix_locus` is required on every finding you emit** (`rtl` or `spec`). The main thread cannot route a
  finding without it; any finding you emit without `fix_locus` is rejected by the schema.
- **`confidence` belongs on every `fix_locus: "spec"` finding** (omit it otherwise): see the guidance
  above. The minimum `confidence` across your spec-locus findings becomes
  `semantic_gate.spec_confidence`, which gates the kernel's upstream route.
