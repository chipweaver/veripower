# IC Spec Brainstorm Checklist

The brainstorm dialogue is driven by the following dimensions: **one question at a time, multiple-choice preferred.** Decide which specific questions to ask, and which dimensions to skip, based on the known context. **D0 must be asked first** (do not enter D1 until intent is clarified); **D4 must present 2–3 candidate proposals for comparison.**

## brainstorm.md Section Layout

The dialogue walks dimensions D0–D7, but the **written artifact** uses **descriptive** section headers — one per dimension reached. (The `## Dx.` headers in this checklist are **dialogue labels**, not artifact headers.)

- `## Overview` — D0
- `## Functions & Features` — D1
- `## Interfaces & Interconnects` — D2
- `## Clocks & Reset` — D3
- `## Architecture Candidates` — D4
- `## Timing Scenarios` — D5
- `## PPA Targets` — D6
- `## Verification Inputs Readiness` — D7
- `## Document Control` — revision notes (no dimension)

Omit any dimension not reached. Headers stay descriptive, **never** literal `## D0.`; `Dx` survives only as the dialogue / cross-skill provenance label (specification cites e.g. "ppa_targets ← D6").

## Q&A Style: Options + Recommendation

Every question follows this format:

1. List 2–4 candidate options (A/B/C[/D]), one short sentence per option.
2. End with one line: `Recommend X: <one-sentence rationale>`.

User responses:
- Option label ("A" / "B") → record the choice, advance to the next dimension.
- Custom value → record the custom value, advance to the next dimension.
- Follow-up question → expand the candidate options in more detail.

Format example:

> D3 Clocks and Reset:
>
> - A: single clock 200 MHz / async active-low reset
> - B: dual clock (200 MHz data + 50 MHz config) / async active-low reset
> - C: single clock 100 MHz / sync reset
>
> Recommend A: single clock is simplest; 200 MHz leaves ample synthesis margin.

D0 (intent and scope) is open-ended Q&A and does not follow this format.
D4 (architecture partitioning candidates): 2–3 candidates with side-by-side mermaid diagrams; the recommendation is annotated separately; the user makes the explicit selection.

## D0. Intent and Scope (intent-first)

Open-ended Q&A; may span 2–3 rounds. Do not enter D1 until intent is clarified.

- The module's role in the system (input / output / who it serves).
- The core problem to be solved.
- Scope boundaries (explicitly excluded functionality).
- Hard constraints from upstream and downstream modules (interface specifications, protocol versions, SoC layout).
- Project phase (greenfield / replacement / backward-compatible / exploratory prototype).

Closure signal: you restate the module's intent accurately in 1–2 sentences and the user confirms. Record under `Overview` in brainstorm.md.

## D1. Functions and Features

- Module's core function (1–2 sentences).
- Main feature list (each item has `ID` / description / priority).
- For each feature: a Happy path + at least 1 corner case + at least 1 negative case.
- Are there operating-mode switches? (e.g., slave/master, bypass/active.)
- **Critical numeric parameter lock**: if a feature involves a deterministic latency / byte width / state-machine cycle count or any other numeric quantifiable from a reference implementation, it must be settled at this dimension (value + source rationale) — do not defer it to the design.md authoring stage. Otherwise, the Write-after-correction pattern (a wrong first draft → multiple Edits on the main thread) appears during the design.md authoring stage.

## D2. Interfaces and Interconnects

D2 covers two related but separate concerns:

**D2a Top-Level IO**: DUT-boundary signals (signal name / direction / width /
clock domain / protocol). Output: `top-io.json`.

- List of top-level interface groups (one name per group, e.g., `cfg_bus` / `data_in` / `status_out`).
- Protocol type per group (AXI-lite / APB / valid-ready / streaming / custom).
- Clock domain each group belongs to.
- Backpressure strategy (blocking / drop / overwrite).

**D2b Inter-module Interconnects** (fan-out mode only; can be empty for
N=1 modules): wires between RTL modules (Producer / Consumer at RTL-module
level / Protocol / Timing). Output: `interconnects.json`. Each cross-child wire is **declared once** there;
sub-design `<child>.md §2 Interface` references but does not redefine.

## D3. Clocks and Reset

- Clock list (name / nominal frequency in MHz / SDC period in ns).
- Are there cross-clock-domain crossings? Synchronization strategy per crossing (Gray / handshake / async FIFO / 2-flop).
- Reset strategy (async low / sync / multi-domain independent resets) — **polarity + sync/async must be explicitly settled**, not deferred to the design.md / SDC stage.
- Reset release ordering constraints (when there are multiple resets).

## D4. Architecture Partitioning Candidates (2–3 candidates mandatory)

Cover at least the following decision dimensions; for each, present 2–3 candidates with a recommendation + one-sentence rationale:

- Pipeline stage count selection.
- Resource sharing vs. duplication (parallel paths).
- Centralized vs. distributed state machines.
- FIFO / buffer size and placement.

Rendering conventions (side-by-side mermaid) are documented in `${CLAUDE_PLUGIN_ROOT}/skills/specification/references/design-template.md` §Rendering Conventions. Side-by-side example:

### Candidate A: 2-stage pipeline

```mermaid
flowchart LR
  IN --> S1[Stage 1] --> S2[Stage 2] --> OUT
```

### Candidate B: 3-stage pipeline

```mermaid
flowchart LR
  IN --> S1[Stage 1] --> S2[Stage 2] --> S3[Stage 3] --> OUT
```

## D5. Timing Scenarios

- Typical transactions (at least 1 happy-path scenario).
- Back-to-back / backpressure scenarios.
- Exception scenarios (timeout, illegal request, reset interrupting a transaction).
- For each scenario: `trigger/stimulus → expected result → timing constraint`.

Rendering conventions (hand-drawn ASCII preferred / wavedrom — note that GitHub does not render wavedrom) are documented in `${CLAUDE_PLUGIN_ROOT}/skills/specification/references/design-template.md` §Rendering Conventions; an ASCII timing example is in design-template.md §1.5.

## D6. PPA Targets

- Is PPA optimization required?
- If so, which dimensions are on the list (`area_um2` / `timing_slack_ns` / `power_mw`)?
- Target value for each listed dimension.
- If PPA optimization is not pursued: record explicitly as an empty list (`[]`), distinguishing from "never asked" (field missing).

## D7. Verification Input Field Readiness

Cross-check, row by row, against the "Minimum Field Completeness Gate Table" at the end of `${CLAUDE_PLUGIN_ROOT}/skills/specification/references/design-template.md` — the required items are the `features.json` / `timing-scenarios.json` / `top-io.json` / `interconnects.json` / `check-hints/<child>.json` rows in that table. The brainstorm only acts as a reminder; the actual fields land during the design.md authoring stage. Missing items are called out by name in the `Verification Inputs Readiness` section of brainstorm.md.

## Subsection IDs and Stable Anchors

The objective coverage gate (`check-coverage`) and the manifest's per-child `brainstorm_anchor` line ranges trace at **brainstorm subsection granularity**, so brainstorm.md must carry stable, reusable names:

- Each row of the D1 feature table carries a stable `ID` (recommended `F-NN`) — `features.json` reuses it directly as `id`, and the child frontmatter `features ⊆ features.json` subset check keys on it.
- D2a top-level interface groups + D2b inter-module wire names, D4 candidates, D5 scenario table all use reusable named anchors (e.g., `cfg_bus` / `Candidate B` / `SC-001`).
- D6 must explicitly write `ppa_targets: []` even when PPA optimization is not pursued, distinguishing "asked and decided none" from "forgot to ask."
- Open questions use numbering like `OQ-NN` so they remain locatable.

Stable IDs keep the feature/clock/port subset checks cross-referenceable — those key on names (`F-NN`, a clock name, a port name), never on position. `brainstorm_anchor` still records which passage is primarily a child's, but nothing requires every chapter to fall inside some child's range: the spec-review reviewer reads the whole document, so a chapter no child claims is not a defect.

## Open-Question Usage Rules

- For topics not covered by D1–D7: open questions may be appended.
- Trigger condition: the user introduces a new boundary condition / constraint / technical choice.
- Every open question must also be settled (do not leave TBD in brainstorm.md).

## Revision Mode Trimming Rules

> **Scope**: only the revision-mode re-invocation of this skill (brainstorm SKILL.md Workflow Step 5), where a requirements change prompts a re-run against an existing brainstorm.md.

- Compare against the existing `brainstorm.md`, and only re-ask **the D dimensions affected by this requirements change**.
- D0 can usually be skipped (intent unchanged), but if the change hints at intent drift (e.g., "the original module positioning no longer fits"), still do a round of mini-D0.
- If this is a PPA change: re-ask at least D4 (architecture partitioning) + D6 (whether PPA targets need adjustment).
- Skip all other dimensions; in brainstorm.md's Document Control Notes, note which dimensions this round did not touch (e.g., "this round did not touch D0/D1/...").
