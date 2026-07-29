# Spec semantic review sub-Task contract (gating)

The specification main thread dispatches a Level-1 per-child review wave **on every finalize that
reaches a clean coverage gate** (Step 7), AFTER `check-coverage` is green and BEFORE the
design.md approval gate. This review is **gating**: `faithfulness` AND `conformance` findings at
`severity ∈ {critical, important}` BLOCK the stage from `status=pass` until resolved; `soundness`
findings are advisory **must-acknowledge** (surfaced to the user, never block). The main thread
does NOT auto-fix design.md — a blocking finding is resolved by user-directed rework. Do not call the Task tool.

## Per-child reviewer (one per `manifest.children[]`)

### Inputs (paths only — the main thread reads no body)
- The child's per-child design doc, located via `manifest.children[<self>].doc`.
- `asic/{module}/brainstorm.md`, **read all of it** — the frozen statement of *intent* to check
  faithfulness against. Read-scope was once the child's `brainstorm_anchor` slice; it is the whole
  document because the slices do not cover it (on a real module 53% of the lines fell in no child's
  anchor) and because slicing presumes the brainstorm's shape, which a human-authored dialogue does
  not owe us. Your child's anchor still tells you which passage is PRIMARILY yours — start there,
  but a formula or constraint stated anywhere in the document is in scope for judging whether your
  child realizes the intent.
- `design.md` path, read-scope §1.4 only (top IO / interconnects, **including the §1.4.x Encoding
  field and the §1.4.2.1 Inter-module Behavior Contract companion when present**), as both
  integration context and the conformance reference frame.

### Your job: skeptical intent review of the SPEC (NOT RTL / lint / PPA)
You are a fresh reviewer. **Do not trust that the spec is correct because it is written.**
Read the `<child>.md` against the brainstorm intent (your anchor marks your primary passage; the document as a whole is the frame) and against `design.md` §1.4. Three lenses:
- **`faithfulness`** (gating) — does `<child>.md` completely and correctly realize the brainstorm
  intent for this child, with nothing omitted, contradicted, or silently added? (reference frame =
  the whole brainstorm.md). Examples: a brainstorm-required mode/signal/behavior absent from the doc;
  a doc decision that contradicts a brainstorm requirement.
- **`conformance`** (gating, reference frame = `design.md` §1.4.x Encoding) — for each **control/status**
  §1.4.x row this child consumes or drives:
  - **(1) Encoding present AND adequate** — does the row pin an Encoding complete enough that the
    consumer can implement its decode/obligation with no guessing (a code→symbol with the per-code
    consumer obligation for a phase/command bus)? A missing or under-specified (thin) Encoding is a
    `conformance` finding.
  - **(2) Decode agrees with the row** — does this child's `<child>.md §2/§3` decode / obligation
    **agree with the pinned Encoding row** (no divergent decode, no contradicted obligation)? Decision
    rule: a well-formed-but-inadequate Encoding, or a child decode/obligation that contradicts a
    well-formed row, is `conformance` (block).
  - **Name-resolution** for an inter-module behavior contract — when **two or more `interconnects.json` wires
    reference the same named phase / sequence** (in their `Timing Constraint` cells or control-bus
    `Encoding` symbols) but that name is **not declared in the §1.4.2.1 companion** — including the case
    where such named references exist yet there is no companion at all — the references do not resolve,
    and that is a `conformance` finding (block).

  NOTE: there is no deterministic encoding gate — judging adequacy IS your job here (do not assume a
  mechanical check caught it). The conformance block line is **encoding decode/adequacy + name-resolution
  only** — both objective. Two things are NOT conformance (report as `soundness` advisory, never block):
  (a) whether this module *ought* to have a joint contract it never referenced (a pure judgment, like
  deciding what counts as control/status); (b) whether the stated co-assertions / relative offsets /
  mutual-exclusion are *correct*, or whether a coarse symbol resolves to several companion phases
  (ambiguous projection — the reference resolves, but not to one).
- **`soundness`** (advisory must-acknowledge, NO upstream reference — pure design judgment):
  - **Micro-arch realizability** — is the child's spec-introduced micro-architecture (timing
    assumptions, state-machine / datapath choices) logically self-consistent and able to realize the
    required behavior?
  - **Cross-interface inconsistency** that is NOT a `conformance` issue (not an encoding decode/adequacy
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
  the deterministic cross-file checks `check-coverage` owns (frontmatter subsets, sidecar shapes,
  top-partition purity, anchor resolvability).

### Output
End with `STATUS: DONE` + a single JSON line, or `STATUS: BLOCKED <reason>`:
```json
{"child": "<name>",
 "findings": [{"lens": "faithfulness|conformance|soundness",
               "severity": "critical|important|minor",
               "location": "<child>.md §ref | brainstorm anchor ref", "summary": "<one line>"}]}
```
- The main thread stamps each finding with this `<child>` during aggregation; you need not repeat
  it per finding (the top-level `child` is authoritative).
- **severity:** `critical` = likely-wrong intent realization downstream won't catch cheaply;
  `important` = real concern; `minor` = nit. Calibrate.
