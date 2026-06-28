# Per-child semantic review sub-Task contract (gating)

The rtl-design main thread dispatches one Level-1 `Task(run_in_background=True)` per child
in `manifest.children[]` **on every finalize that reaches a clean gate** (not first-run only),
AFTER the conformance gate (`check-conformance`) is green. This review is **gating**: findings
in `category ∈ {missing, wrong-behavior}` at `severity ∈ {critical, important}` trip a gate that
fails the stage out (`status=fail`) to the operator. `over-engineering` and `minor` findings
remain advisory (never gate). Findings are aggregated into `semantic-review.json`. Do not call the Task tool.

## Inputs (paths only — the main thread does not read these bodies)

- Child unit name + its `manifest.children[<self>].rtl_modules[]` list.
- The child's authored RTL `files[]` (from the ledger) — read these.
- The child's per-child design doc, located via `manifest.children[<self>].doc` (the registry SSoT —
  the SAME path authoring uses; do NOT hardcode `Design/specification/<child>.md`, which can drift from
  the deployed layout). **Read its §2 Interface (and, for the top-integration child, the §3.1
  instantiation map = §1.4.2 restatement)** as the statement of *intent* to check against.
- `design.md` path, read-scope §1.4 only (top IO / interconnects), for cross-checking integration intent.

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

**Out of scope (do NOT report):** synthesizability / timing / area / power (downstream stages);
lint / CDC rule violations (lint-cdc); pure syntax (the child self-lints); spec↔RTL *presence*
mismatches (the deterministic `check-conformance` gate already covers these).

## Output

End the response with `STATUS: DONE` + a single JSON line, or `STATUS: BLOCKED <reason>`:

```json
{"child": "<name>", "verdict": "ok|concerns",
 "findings": [{"severity": "critical|important|minor",
               "category": "missing|wrong-behavior|over-engineering",
               "fix_locus": "rtl|spec",
               "location": "<file:line or <child>.md §2 ref>", "summary": "<one line>"}]}
```

- `verdict": "ok"` ⟺ `findings` empty. `"concerns"` ⟺ ≥1 finding.
- **severity guidance:** `critical` = likely wrong functionality that downstream may not catch cheaply;
  `important` = real concern worth a look; `minor` = nit. Calibrate — not everything is critical.
- **`fix_locus` is required on every finding you emit** (`rtl` or `spec`). The main thread cannot route a
  finding without it; any finding you emit without `fix_locus` is rejected by the schema.
