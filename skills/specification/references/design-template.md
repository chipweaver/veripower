# design.md Section Template

`{workdir}/design.md` is the **design source of truth** produced by this skill: §1.1–1.6 describe the module as a whole (function, interfaces, timing, frequencies, architecture partitioning), and the §1.7 submodule index points to each child's `<child>.md`, where the per-submodule implementation detail lives. All external consumers (RTL implementation / constraint generation / verification derivation / synthesis / power / timing signoff, etc.) read from `design.md` and these child docs.

> **`design.md` self-containment principle**: all critical invariants from brainstorm (RTL formulas / interface timing / numeric parameters / implementation constraints / overlay explicit spec supplement sections) must be inlined verbatim into `design.md`. **By-reference jumps are forbidden** (such as "see brainstorm §sd_clock_divider IO Ports" / "see spec D2" / "refer to brainstorm section sd_controller_wb" / "see brainstorm §X"). The downstream skill input lists do not literally include `brainstorm.md`; by-reference = information loss, which causes false-fail under cycle-accurate `===` checks. Enforced by `check-coverage`.

## Document Position

| Section range | Responsibility |
|---|---|
| 1.1–1.6 Overview sections | Function, interfaces, timing, frequencies, architecture partitioning; 1:1 consistent with each D-dimension field in brainstorm.md; on conflict, this section is the single upper-layer authority. `constraints/<TOP>.{sdc,sgdc}` is regenerated from §1.6 by `derive-constraints`, never hand-edited. |
| 1.7 Submodule Index | Pointer table to each child's `<child>.md` (name / doc / brainstorm anchor / role); the per-submodule implementation detail (FIFO / arbitration / exceptions / state-machine boundaries / register side effects, etc.) lives in those child docs, not here. On conflict between an overview table and a child doc, **fix the overview first**. |
| 2 Document control | Version, revision notes, the corresponding (frozen / approved) brainstorm.md. |

## Rendering Conventions

| Content type | Recommended format | Notes |
|----------|----------|------|
| Architecture diagrams (§1.2 / submodule `<child>.md` bodies / brainstorm D4 candidates) | mermaid code block | GitHub / VSCode preview / mkdocs all render natively; for multiple side-by-side candidates use one code block each. |
| Timing diagrams (§1.5 interface timing / brainstorm D5 scenarios) | Hand-drawn ASCII (preferred) or wavedrom | wavedrom does **not** render on GitHub — if wavedrom is used, attach an ASCII equivalent or export a PNG when reviewing the PR; otherwise stick with ASCII. |

Each timing diagram must be paired with a textual description that **maps one-to-one onto each phase of the waveform** (setup/hold, handshake meaning, typical/boundary cycles, etc.). This convention applies to both `brainstorm.md` and `design.md`.

## Overview Section Template (1.1–1.6)

```markdown
# <module_name> Design Document (design.md)

## 1. Module Overview

### 1.1 Overview
(Module description: role in the system, core problem solved, scope boundaries.)

PPA targets: see `ppa.json` (numeric target values live there only — do not restate them
in prose; synthesis / power-analysis bind to that file directly).

### 1.2 Module Structure
(Architecture diagram + table of submodules and primary functions.)

```mermaid
flowchart LR
  A[Sub-A] --> B[Sub-B] --> C[Sub-C]
```

| Submodule | Primary Function |
|---|---|
| Sub-A | … |
| Sub-B | … |

### 1.3 Feature Table

The feature list lives in `features.json` (the spine child §5 `SourceFeature` rows and
testpoints refer to). Do not restate features in prose. Narrative that is not a per-feature
field belongs here: how the features partition the module, which are out of scope.

### 1.4 Module Interface and Interconnects

#### 1.4.1 Top-Level IO

| Signal | Direction | Owner | Width | Clock Domain | Interface Group | Protocol | Role | Encoding | ResetPolarity | ResetKind |
|--------|-----------|-------|-------|--------------|-----------------|----------|------|----------|---------------|-----------|
| clk    | input  | - | 1 | clk | clk     | -    | clock | - | -  | -     |
| rst_n  | input  | - | 1 | clk | reset   | -    | reset | - | 0  | async |
| cfg_addr | input | - | 8 | clk | cfg_bus | APB3 | data  | - | -  | -     |

> **Owner** (Output rows): the child that drives this output; input/inout rows use `-`.
> - **Gated** (enforced by `check-coverage`): the Owner is present, is a manifest child, and that child lists the signal in its frontmatter `ports`.
> - **Guidance (not gated):** prefer a **leaf child** that the pure top-integration child passes through to the boundary; an output driven by the top-integration child's own combinational glue (mux / reduction / constant) is discouraged, prefer a dedicated child (e.g. an arbiter). The top-integration child as `Owner` still passes the gate; this preference is a design note, not enforced.

> **Role** (required — `derive-constraints` reads it): `clock` / `reset` / `data`.

> **Encoding** (required content rule — enforced by the spec-review `conformance` lens, NOT a
> deterministic gate): a **control or status** signal MUST pin its bit/field→symbol meaning here.
> Single-bit: `0:<meaning>; 1:<meaning>`. Multi-bit: per field `bit[h:l] <name>: <code>:<symbol>; …`,
> and for a phase/command code write the **consumer obligation**, not just a label
> (e.g. `3:PV (consumer re-preloads the stationary operand, then streams)`). A raw data / clock /
> reset signal uses `-` (no encoded value). The single source of truth is this row; a child restates
> it verbatim, never diverges.

> **ResetPolarity** (reset rows only): `0` = active-low, `1` = active-high.
> **ResetKind** (reset rows only): `sync` / `async`.
> Clock and reset ports carry no IO delay; each `data` port gets
> `set_input/output_delay -clock <Clock Domain>` and an `abstract_port -clock <Clock Domain>`.
> These columns make constraint generation a pure function of this table — no name heuristics.

#### 1.4.2 Inter-module Interconnects

> Fan-out mode (N≥2): authoritative list of all RTL-module-to-RTL-module wires. N=1 modules: keep the §1.4.2 heading with a single `(none — N=1 module has no inter-module wires)` row; do not omit the section (`check-coverage` requires §1.4.2 present).

| Wire | Producer (RTL module) | Consumer (RTL module) | Width | Clock Domain | Protocol | Encoding | Timing Constraint | Notes |
|------|-----------------------|-----------------------|-------|--------------|----------|----------|-------------------|-------|
| … | … | … | … | … | … | … | … | … |

> **Width** and **Clock Domain** are **gated**: every inter-module wire pins a concrete Width (`-` is not valid) and a Clock Domain that is a §1.6 clock name. (Direction is encoded by Producer/Consumer. ResetPolarity/ResetKind are NOT gated on §1.4.2 — reset is enforced only at constraint generation on §1.4.1 `Role=reset` rows.) A heterogeneous control bundle (fields of differing width, e.g. an old `ctrl_bus`) cannot fill one honest Width row — break it into per-field wires. Enforced by `check-coverage`.

> **Encoding** (required content rule — enforced by the spec-review `conformance` lens, NOT a
> deterministic gate): a wire that carries an **encoded control/status value** (a command/phase bus,
> a status/mode bus) MUST pin its bit/field→symbol meaning here, using the same format and
> obligation-semantics rule as §1.4.1 `Encoding`. A raw data wire (e.g. an operand/score beat) uses
> `-`. This row is the single source; producer and consumer children read the same row, so per-wire
> agreement is structural. (Cross-**bus** consistency — multiple control buses that project one FSM —
> is not pinned *in this row*; its joint contract is stated in the §1.4.2.1 Inter-module Behavior
> Contract companion below.)

> **Inter-module Behavior Contract** (required content rule, enforced by the spec-review
> `conformance` lens, NOT a deterministic gate): when a *group* of inter-module wires is governed by
> a contract that **more than one wire / child must jointly agree on** (a shared operating-phase or
> event timeline, a sequencing, a co-assertion or mutual-exclusion among control strobes), that joint
> contract MUST be stated **once** in the `##### 1.4.2.1` companion below, NOT left implicit in one
> child's body (where sibling children and their per-child reviewers cannot see it).
> - A behavior fully captured by a single wire's own row (a plain valid/ready handshake, a
>   single-clock latency) needs no companion.
> - Form adapts to the module: a phase-sequenced datapath states an ordered operating-phase table;
>   a handshake/arbitration module states the co-assertion / mutual-exclusion rule in prose. Per-wire
>   `Timing Constraint` cells and control-bus `Encoding` symbols then reference the names declared in
>   the companion.
> - This pins the *statement* of the contract and the *resolvability* of references to it; the
>   *correctness* of the co-assertions / relative offsets / mutual-exclusion is design judgment
>   (advisory soundness + downstream RTL/sim), not pinned here.

##### 1.4.2.1 Inter-module Behavior Contract

Present **only** when §1.4.2 wires share a joint contract (see the Inter-module Behavior Contract
rule above); omit entirely otherwise. Place it here, **after** the §1.4.2 wire table and its column
notes, so the §1.4.2 wire-table parse is unaffected.

Worked example A — a **phase-sequenced datapath** states an ordered operating-phase timeline;
control buses project onto it (each `Encoding` symbol names its canonical phase(s)) and per-wire
`Timing Constraint` windows reference these phase names:

| # | Phase | Cycles | Notes (projection / co-assertion / boundary, as applicable) |
|---|-------|--------|-------------------------------------------------------------|
| 1 | LOAD    | 12 (handshake) | ctrl_phase=LOAD |
| 2 | PRELOAD | 2N−1           | ctrl_fabric=PRELOAD |
| … | …       | …              | … |

Worked example B — a **handshake / arbitration** module states the joint contract in prose (no
phase table). E.g. a TX/RX start mux:

> `start_tx_fifo` and `start_rx_fifo` are mutually exclusive (never both high). The master-bus
> outputs route to the TX variables when `start_tx_fifo` is high, to the RX variables when
> `start_rx_fifo` is high, else to `0`. Consumers of the muxed bus rely on this exclusion to decode
> the source.

### 1.5 Interface Timing Scenarios

Subdivide by **interface group**; diagrams may be hand-drawn ASCII (preferred) / wavedrom / tool-exported image (rendering and textual-description requirements per §Rendering Conventions). Each scenario row's fields are also subject to "minimum field completeness."

#### Example: a configuration-port write transaction (hand-drawn ASCII)

~~~text
        idle      setup/hold region        transaction done      idle
clk      __|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_
cfg_en   _________|‾‾‾‾‾‾‾‾‾‾‾‾‾|_______________
addr     _________<── ADDR ──>_______________
wdata    _________<── WDATA ─>_______________
rdy      _________|‾‾‾‾‾‾‾‾‾‾‾‾‾|_______________   (slave ready)
~~~

**Textual description (must map one-to-one onto each phase above)**
- **idle**: `cfg_en` low; whether ADDR/WDATA matter is defined by the protocol.
- **setup/hold region**: before/after the valid sampling edge, ADDR and WDATA satisfy *T_setup* / *T_hold* relative to `clk`.
- **transaction done**: when `cfg_en` and `rdy` are both high, the slave accepts this write.
- **return to idle**: after the slave drops `rdy`, the bus enters idle, ready for the next transaction.

#### Timing Scenarios Table

| ScenarioID | Interface/Mode | Trigger/Stimulus | Expected Result | Timing Constraint | Exceptions / Negative Cases |
|------------|-----------|-----------|----------|----------|-----------|
| SC-… | … | … | … | … | … |

### 1.6 Clocks and Frequencies

Clock definitions live in `clocks.json` (the sole numeric + relationship source;
`constraints/<TOP>.{sdc,sgdc}` are generated from it). Do not restate periods,
frequencies or relationships in prose — same single-home rule as §1.1's PPA targets.
Narrative that is NOT a per-clock field belongs here: domain count, CDC posture,
reset scheme, release-ordering constraints.
```

## features.json (§1.3's machine half)

Authored by Wave 1; schema `references/features.schema.json`. A JSON array, one object per
feature. All fields are free prose — no script parses inside a field.

| Field | Rule |
|---|---|
| `id` | Required. What child §5 `SourceFeature` rows and testpoints refer to. |
| `name` | Required. Short label; reaches the TB testlist and the human-read case-results summary. |
| `description` | Required. What the feature is, including any RTL formula that pins it. |
| `mode_interface` | Required. The interface group or operating mode exercised. |
| `priority` | Required free text — the vocabulary is your project's, not the schema's. |
| `happy_path` / `corner_cases` / `negative_cases` | Required and non-empty. |
| `coverage_intent` | Optional. Absent means absent. |

## clocks.json (§1.6's machine half)

Authored by Wave 1 alongside `ppa.json`; schema `references/clocks.schema.json`. A JSON
array, one object per clock:

```json
[
  { "name": "clk",    "freq_mhz": 100, "period_ns": 10.0, "relationship": "primary", "generated": false, "role": "primary clock" },
  { "name": "clk_io", "freq_mhz": 50,  "period_ns": 20.0, "relationship": "async",   "generated": false, "role": "IO-domain clock" }
]
```

| Field | Rule |
|---|---|
| `name` | Required. For a non-generated clock this is also the top-level port name `create_clock` binds to. |
| `freq_mhz` / `period_ns` | Required **numbers** (not strings). `period_ns` must equal `1000 / freq_mhz` — enforced by `check-coverage`. |
| `relationship` | Required, one of `primary` / `synchronous-related` / `async`. `async` drives `set_clock_groups -asynchronous` (SDC) and a distinct `-domain` (SGDC). **Exactly one `primary`** — it is the TB main clock; `derive-constraints` fails loud otherwise. |
| `generated` | Optional (default `false`). `true` for a divider/PLL output with no top-level port: `derive-constraints` emits **no** `create_clock` and records a `create_generated_clock`-deferred-to-RTL note in its place. |
| `role` | Optional free text for human / agent readers. No script parses it. |

`additionalProperties` is `false`: a mistyped key fails at write time, in front of you.

## Submodule Index Template (§1.7)

```markdown
### 1.7 Submodule Index

See `manifest.json` for the authoritative child registry. This table lists child names + brainstorm anchors as a quick reference (concrete content lives in per-child `<child>.md` files; see `child-design-template.md`).

| child name | doc | brainstorm_anchor | role |
|------------|-----|-------------------|------|
| sub_a | `sub_a.md` | lines 40-80 | … |
| sub_b | `sub_b.md` | lines 81-120 | … |
```

For every module (N≥1) the parent `design.md` keeps only this §1.7 index; each child's detail lives in its own `<child>.md` (per `child-design-template.md`), authored by wave-2 — which always dispatches one sub-Task per child (N=1 → ×1, never an inlined submodule body in `design.md`).

## Minimum Field Completeness Gate Table

Before `design.md` is approved, the **gated** checks below must pass `check-coverage`; **recommended** columns degrade downstream quality if absent (`derive-plan-data` defaults them, so a missing column yields an empty/weaker derivation, not a crash). Failing any gated check disqualifies you from marking pass.

| Check | Field location | Impact of missing |
|--------|----------|----------|
| `features.json` fields `id` / `name` / `description` / `mode_interface` / `priority` / `happy_path` / `corner_cases` / `negative_cases` present and non-empty — **(schema)** | `features.json` | Enforced by `features.schema.json` at `check-coverage`. Non-empty is deliberate — a blank field is a defect, not a default. |
| `features.json` field `coverage_intent` — **(optional)** | `features.json` | Absent means absent; nothing substitutes a value for it. |
| §1.4.1 columns Signal / Direction / Clock Domain / Interface Group / Role — **(gated)** | Overview §1.4.1 table | Absent columns degrade constraint and agent generation; `derive-constraints` may emit incomplete IO delays or miss CDC domains. |
| §1.4.1 columns Width / Protocol — **(recommended)** | Overview §1.4.1 table | Absent Width defaults to `1`; absent Protocol yields empty protocol annotations. |
| §1.4.1 columns ResetPolarity / ResetKind — **required on `Role=reset` rows** (enforced at constraint generation by `derive-constraints`, which fail-louds on a reset row missing them — not by the coverage gate; use `-` on non-reset rows) | Overview §1.4.1 table | A reset row missing polarity/kind aborts `derive-constraints`. |
| §1.5 columns ScenarioID / Trigger/Stimulus / Expected Result / Timing Constraint — **(gated)** | Overview §1.5 table | Missing any of these fails `check-coverage`; they drive downstream sequence-body and checker generation (via `derive-plan-data`). |
| §1.5 column Exceptions / Negative Cases — **(recommended)** | Overview §1.5 table | Absent column degrades negative-case coverage; `derive-plan-data` defaults it to empty. |
| `clocks.json` fields `name` / `freq_mhz` / `period_ns` / `relationship` present and correctly typed — **(schema)** | `clocks.json` | Enforced by `clocks.schema.json` at `derive-constraints`, which fails loud. A mistyped key is named in the error, not silently defaulted. |
| `clocks.json` declares exactly one `relationship: "primary"` — **(gated)** | `clocks.json` | Not schema-expressible; `derive-constraints` fails loud. It is the TB main clock — an ambiguous set would let a downstream reader pick arbitrarily. |
| `clocks.json` internal consistency: `period_ns` ≈ `1000 / freq_mhz` per entry — **(gated)** | `clocks.json` | A freq/period typo would propagate into every generated `create_clock`; enforced by `check-coverage`. |
| §1.4.1 `Clock Domain` values ⊆ `clocks.json` `name`s — **(gated)** | §1.4.1 table + `clocks.json` | A phantom domain would make `abstract_port -clock <phantom>` and break SpyGlass CDC; enforced by `check-coverage`. |
| §1.4.1 every Output has an `Owner` that is a manifest child listing the signal — **(gated)** | §1.4.1 Owner column + per-child frontmatter | A missing/invalid Owner, or an Owner child that does not list the signal, is an undriven / mis-declared top output; enforced by `check-coverage`. (The leaf-owner / no-top-glue preference is documented guidance, not gated.) |
| §1.4.2 columns Width / Clock Domain present + per-row concrete — **(gated)** | Overview §1.4.2 table | Unpinned inter-module width lets body-blind fan-out children diverge (the fa_core 128b↔32b / opaque-`ctrl_bus` class); enforced by `check-coverage`. |
| §1.4.2 `Clock Domain` values ⊆ `clocks.json` `name`s — **(gated)** | §1.4.2 table + `clocks.json` | A phantom interconnect domain hides a CDC path; enforced by `check-coverage`. |
| Every `features.json` `id` referenced by ≥1 child §5 `SourceFeature` — **(gated)** | `features.json` + per-child `<child>.md §5` | Catches specified-but-unverified features; enforced by `check-coverage`. |
| `<child>.md §5` Verification-Hints table has the **gated** columns CheckID / SourceFeature / ImplementationDetail / Observable / ReferenceRule (Latency / ResetBehavior recommended; ImplementationDetailVerbatim is guarded by token-survival, BrainstormAnchor is traceability) | per-child `<child>.md §5` (see `child-design-template.md`) | Cannot generate rule-based RM / scoreboard; **enforced by `check-coverage`**. |
| `design.md` self-containment (no `see brainstorm` / `refer to brainstorm` / `see spec D` / cross-child links) | Whole document + each `<child>.md` | See the self-containment principle stated once above; **enforced by `check-coverage`**. |

> Derivation rules, UVM field mapping, and a complete derivation-chain example are owned by `veripower:simulation-plan`. You do not need to read them; you only need to ensure every check in this table lands in the table columns.

## Document Control

```markdown
## 2. Document Control

| Version | Date | Notes | brainstorm.md |
|------|------|------|---------------------|
| 0.1 | YYYY-MM-DD | Initial draft | approved |
```
