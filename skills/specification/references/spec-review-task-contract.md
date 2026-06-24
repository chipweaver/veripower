# Spec semantic review sub-Task contract (gating)

The specification main thread dispatches a Level-1 per-child review wave **on every finalize that
reaches a clean coverage gate** (Step 7), AFTER `check_coverage.py` is green and BEFORE the
design.md approval gate. This review is **gating** (T2): `faithfulness` AND `conformance` findings at
`severity ∈ {critical, important}` BLOCK the stage from `status=pass` until resolved; `soundness`
findings are advisory **must-acknowledge** (surfaced to the user, never block). The main thread
does NOT auto-fix design.md — a blocking finding is resolved by user-directed rework. A dispatched
sub-Task MUST NOT call the Task tool.

## Per-child reviewer (one per `manifest.children[]`)

### Inputs (paths only — the main thread reads no body)
- The child's per-child design doc, located via `manifest.children[<self>].doc`.
- `asic/{module}/brainstorm.md`, read-scope = the child's `manifest.children[<self>].brainstorm_anchor`
  slice — the frozen statement of *intent* to check faithfulness against.
- `design.md` path, read-scope §1.4 only (top IO / interconnects, **including the §1.4.x Encoding
  column and the §1.4.2.1 Inter-module Behavior Contract companion when present**), as both
  integration context and the conformance reference frame.

### Your job: skeptical intent review of the SPEC (NOT RTL / lint / PPA)
You are a fresh reviewer. **Do not trust that the spec is correct because it is written.**
Read the `<child>.md` against its `brainstorm_anchor` intent and against `design.md` §1.4. Three lenses:
- **`faithfulness`** (gating) — does `<child>.md` completely and correctly realize the brainstorm
  intent for this child, with nothing omitted, contradicted, or silently added? (reference frame =
  brainstorm.md slice). Examples: a brainstorm-required mode/signal/behavior absent from the doc;
  a doc decision that contradicts a brainstorm requirement.
- **`conformance`** (gating) — for each **control/status** §1.4.x row this child consumes or drives:
  (1) does the row pin an Encoding that is **present AND adequate** — i.e. complete enough that the
  consumer can implement its decode/obligation with no guessing (a code→symbol with the per-code
  consumer obligation for a phase/command bus)? a missing or under-specified (thin) Encoding is a
  `conformance` finding; (2) does this child's `<child>.md §2/§3` decode / obligation **agree with
  the pinned Encoding row** (no divergent decode, no contradicted obligation)? (reference frame =
  `design.md` §1.4.x Encoding). Decision rule: a well-formed-but-inadequate Encoding, or a child
  decode/obligation that contradicts a well-formed row, is `conformance` (block). NOTE: there is no
  deterministic encoding gate — judging adequacy IS your job here (do not assume a mechanical check
  caught it).
  Additionally, **name-resolution** for an inter-module behavior contract: when **two or more §1.4.2
  wires reference the same named phase / sequence** (in their `Timing Constraint` cells or control-bus
  `Encoding` symbols) but that name is **not declared in the §1.4.2.1 companion** — including the case
  where such named references exist yet there is no companion at all — the references do not resolve,
  and that is a `conformance` finding (block). The conformance block line is **encoding decode/adequacy
  + name-resolution only** — both objective. Two things are NOT conformance (report as `soundness`
  advisory, never block): (a) whether this module *ought* to have a joint contract it never referenced
  (a pure judgment, like deciding what counts as control/status); (b) whether the stated
  co-assertions / relative offsets / mutual-exclusion are *correct*, or whether a coarse symbol
  resolves to several companion phases (ambiguous projection — the reference resolves, but not to one).
- **`soundness`** (advisory must-acknowledge) — is the child's spec-introduced micro-architecture
  (timing assumptions, state-machine / datapath choices) logically self-consistent and able to
  realize the required behavior? (NO upstream reference — pure design judgment). **Also report here**
  any cross-interface inconsistency that is NOT a `conformance` issue (not an encoding decode/adequacy
  defect, not a behavior-contract name-resolution failure — those block above). In particular the
  **correctness** of a cross-bus behavior contract — whether co-assertions / relative offsets /
  mutual-exclusion are right, whether a **coarse control-bus symbol resolves to several companion
  phases (ambiguous projection)**, and any cross-**bus** phase-fold you cannot fully verify from one
  child — is advisory soundness; downstream RTL semantic-review / simulation is the backstop.

### Out of scope (do NOT report as faithfulness)
- **Width / Clock-Domain / Owner mechanical defects** — these are the deterministic §1.4.x coverage
  gate's job (Step 6). If you nonetheless observe one, report it as `soundness` (advisory), never
  `faithfulness`. (Encoding presence/adequacy is NOT in this mechanical set — there is no
  deterministic encoding gate; it is the `conformance` lens above.)
- RTL correctness (no RTL exists yet); lint / CDC / timing / area / power (downstream stages);
  structural coverage (the `check_coverage.py` gate already covers it).

### Output
End with `STATUS: DONE` + a single JSON line, or `STATUS: BLOCKED <reason>`:
```json
{"child": "<name>", "verdict": "ok|concerns",
 "findings": [{"lens": "faithfulness|conformance|soundness",
               "severity": "critical|important|minor",
               "location": "<child>.md §ref | brainstorm anchor ref", "summary": "<one line>"}]}
```
- `verdict": "ok"` ⟺ `findings` empty; `"concerns"` ⟺ ≥1 finding.
- The main thread stamps each finding with this `<child>` during aggregation; you need not repeat
  it per finding (the top-level `child` is authoritative).
- **severity:** `critical` = likely-wrong intent realization downstream won't catch cheaply;
  `important` = real concern; `minor` = nit. Calibrate.
