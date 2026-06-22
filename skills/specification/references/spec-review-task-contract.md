# Spec semantic review sub-Task contract (gating)

The specification main thread dispatches a Level-1 per-child review wave **on every finalize that
reaches a clean coverage gate** (Step 6.5), AFTER `check_coverage.py` is green and BEFORE the
design.md approval gate. This review is **gating** (T2): `faithfulness` findings at
`severity ∈ {critical, important}` BLOCK the stage from `status=pass` until resolved; `soundness`
findings are advisory **must-acknowledge** (surfaced to the user, never block). The main thread
does NOT auto-fix design.md — a blocking finding is resolved by user-directed rework. A dispatched
sub-Task MUST NOT call the Task tool.

## Per-child reviewer (one per `manifest.children[]`)

### Inputs (paths only — the main thread reads no body)
- The child's per-child design doc, located via `manifest.children[<self>].doc`.
- `asic/{module}/brainstorm.md`, read-scope = the child's `manifest.children[<self>].brainstorm_anchor`
  slice — the frozen statement of *intent* to check faithfulness against.
- `design.md` path, read-scope §1.4 only (top IO / interconnects), for integration context.

### Your job: skeptical intent review of the SPEC (NOT RTL / lint / PPA)
You are a fresh reviewer. **Do not trust that the spec is correct because it is written.**
Read the `<child>.md` against its `brainstorm_anchor` intent. Two lenses:
- **`faithfulness`** (gating) — does `<child>.md` completely and correctly realize the brainstorm
  intent for this child, with nothing omitted, contradicted, or silently added? (reference frame =
  brainstorm.md slice). Examples: a brainstorm-required mode/signal/behavior absent from the doc;
  a doc decision that contradicts a brainstorm requirement.
- **`soundness`** (advisory must-acknowledge) — is the child's spec-introduced micro-architecture
  (interface contracts, timing assumptions, state-machine / datapath choices) logically
  self-consistent and actually able to realize the required behavior? (NO upstream reference —
  pure design judgment). **Also report here:** any cross-interface inconsistency you happen to
  observe between your child's §2 and `design.md` §1.4 (there is no dedicated cross-child reviewer
  this round — report it as `soundness`, advisory).

### Out of scope (do NOT report as faithfulness)
- **Mechanically-decidable interconnect defects** — width vs range / direction / sentinel /
  missing-line completeness is the deterministic §1.4.2 coverage gate's job (Step 6) / Layer-1.
  Layer-1's width-vs-range check is NOT yet implemented; **if you nonetheless observe such a
  defect, report it as `soundness` (advisory), never `faithfulness`** — do not let a mechanical
  defect trip the blocking gate.
- RTL correctness (no RTL exists yet); lint / CDC / timing / area / power (downstream stages);
  structural coverage (the `check_coverage.py` gate already covers it).

### Output
End with `STATUS: DONE` + a single JSON line, or `STATUS: BLOCKED <reason>`:
```json
{"child": "<name>", "verdict": "ok|concerns",
 "findings": [{"lens": "faithfulness|soundness",
               "severity": "critical|important|minor",
               "location": "<child>.md §ref | brainstorm anchor ref", "summary": "<one line>"}]}
```
- `verdict": "ok"` ⟺ `findings` empty; `"concerns"` ⟺ ≥1 finding.
- The main thread stamps each finding with this `<child>` during aggregation; you need not repeat
  it per finding (the top-level `child` is authoritative).
- **severity:** `critical` = likely-wrong intent realization downstream won't catch cheaply;
  `important` = real concern; `minor` = nit. Calibrate.
