# Per-child semantic review sub-Task contract (advisory)

The rtl-design main thread dispatches one Level-1 `Task(run_in_background=True)` per child
in `manifest.children[]` **on every finalize that reaches a clean gate** (not first-run only),
AFTER the conformance gate (`check_rtl_conformance`) is green. This review is **advisory** — it never
changes the stage `status`; its findings are aggregated into `semantic-review.json`. A dispatched
sub-Task MUST NOT call the Task tool.

## Inputs handed to the child (paths only — the main thread does not read these bodies)

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

**Out of scope (do NOT report):** synthesizability / timing / area / power (downstream stages);
lint / CDC rule violations (lint-cdc); pure syntax (the child self-lints); spec↔RTL *presence*
mismatches (the deterministic `check_rtl_conformance` gate already covers these).

## Output

End the response with `STATUS: DONE` + a single JSON line, or `STATUS: BLOCKED <reason>`:

```json
{"child": "<name>", "verdict": "ok|concerns",
 "findings": [{"severity": "critical|important|minor",
               "category": "missing|wrong-behavior|over-engineering",
               "location": "<file:line or <child>.md §2 ref>", "summary": "<one line>"}]}
```

- `verdict": "ok"` ⟺ `findings` empty. `"concerns"` ⟺ ≥1 finding.
- **severity guidance:** `critical` = likely wrong functionality that downstream may not catch cheaply;
  `important` = real concern worth a look; `minor` = nit. Calibrate — not everything is critical.
