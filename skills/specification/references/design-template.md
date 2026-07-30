# design.md Section Template

`{workdir}/design.md` is the **design source of truth** produced by this skill: §1.1–1.6 describe the module as a whole (function, interfaces, timing, frequencies, architecture partitioning), and §1.7 points at `manifest.json`, whose `doc` field locates each child's `<child>.md`, where the per-submodule implementation detail lives. All external consumers (RTL implementation / constraint generation / verification derivation / synthesis / power / timing signoff, etc.) read from `design.md` and these child docs.

> **`design.md` self-containment principle**: all critical invariants from brainstorm (RTL formulas / interface timing / numeric parameters / implementation constraints / overlay explicit spec supplement sections) must be inlined verbatim into `design.md`. **By-reference jumps are forbidden** (such as "see brainstorm §sd_clock_divider IO Ports" / "see spec D2" / "refer to brainstorm section sd_controller_wb"). The downstream skill input lists do not literally include `brainstorm.md`; by-reference = information loss, which causes false-fail under cycle-accurate `===` checks. Judged by the spec-review faithfulness lens, not by a deterministic check — no phrasing blacklist can cover the ways a jump can be worded.

> **Single home**: every per-field fact lives in exactly one place — its sidecar. Each §1.x below
> points at its sidecar and carries only the narrative no field can hold: why the boundary is
> what it is, how the children divide the datapath, what is out of scope. Never restate a field
> value in prose or in a second table. Two hand-written homes for one fact diverge, and the
> divergence is invisible until a reader trusts the wrong one. (Brainstorm content is still
> inlined verbatim per the principle above — that is content, not fields.)

## Document Position

| Section range | Responsibility |
|---|---|
| 1.1–1.6 Overview sections | Function, interfaces, timing, frequencies, architecture partitioning; 1:1 consistent with each D-dimension field in brainstorm.md; on conflict, this section is the single upper-layer authority. `constraints/<TOP>.{sdc,sgdc}` is regenerated from §1.6 by `derive-constraints`, never hand-edited. |
| 1.7 Submodule Index | A pointer to `manifest.json`, the child registry (`name` / `doc` / `rtl_modules` / `brainstorm_anchor`). The per-submodule implementation detail (FIFO / arbitration / exceptions / state-machine boundaries / register side effects, etc.) lives in the child docs. |
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

PPA targets: see `ppa.json` (synthesis / power-analysis bind to that file directly).

### 1.2 Module Structure

The child roster lives in `manifest.json`. Here: the architecture diagram the manifest cannot
hold — dataflow direction, which cut edges carry backpressure, why the partition falls where it
does.

```mermaid
flowchart LR
  A[Sub-A] --> B[Sub-B] --> C[Sub-C]
```

### 1.3 Feature Table

The feature list lives in `features.json` (the spine `check-hints/<child>.json`
`source_feature` values and testpoints refer to). Here: how the features partition the module,
which are out of scope.

### 1.4 Module Interface and Interconnects

#### 1.4.1 Top-Level IO

The port list lives in `top-io.json`. Here: what the boundary is for, which groups exist and
why.

#### 1.4.2 Inter-module Interconnects

The wire list lives in `interconnects.json` (authoritative for every RTL-module-to-RTL-module
cut edge; an N=1 module writes an empty array). Here: how the children divide the datapath.

> **Inter-module Behavior Contract** (required content rule, enforced by the spec-review
> `conformance` lens, NOT a deterministic gate): when a *group* of inter-module wires is governed by
> a contract that **more than one wire / child must jointly agree on** (a shared operating-phase or
> event timeline, a sequencing, a co-assertion or mutual-exclusion among control strobes), that joint
> contract MUST be stated **once** in the `##### 1.4.2.1` companion below, NOT left implicit in one
> child's body (where sibling children and their per-child reviewers cannot see it).
> - A behavior fully captured by a single wire's own entry (a plain valid/ready handshake, a
>   single-clock latency) needs no companion.
> - Form adapts to the module: a phase-sequenced datapath states an ordered operating-phase table;
>   a handshake/arbitration module states the co-assertion / mutual-exclusion rule in prose. A wire's
>   `timing_constraint` and a control bus's `encoding` in `interconnects.json` then reference the
>   names declared in the companion.
> - This pins the *statement* of the contract and the *resolvability* of references to it; the
>   *correctness* of the co-assertions / relative offsets / mutual-exclusion is design judgment
>   (advisory soundness + downstream RTL/sim), not pinned here.

##### 1.4.2.1 Inter-module Behavior Contract

Present **only** when the `interconnects.json` wires share a joint contract (see the Inter-module
Behavior Contract rule above); omit entirely otherwise.

Worked example A — a **phase-sequenced datapath** states an ordered operating-phase timeline;
control buses project onto it (each `encoding` symbol names its canonical phase(s)) and per-wire
`timing_constraint` windows reference these phase names:

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

Subdivide by **interface group**; diagrams may be hand-drawn ASCII (preferred) / wavedrom / tool-exported image (rendering and textual-description requirements per §Rendering Conventions).

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

One entry per interface timing scenario, next to the waveform it belongs to. Give each a
stable `SC-NNN` id — simulation-plan authors one sequence per id and refers back by it — then
say what is driven, what is observable, and the timing obligation. Prose; the shape is yours.

| ID | Interface / mode | Stimulus | Expected | Timing constraint |
|---|---|---|---|---|
| SC-001 | APB / write | Legal-address write transaction | `pready` high within 1–2 cycles, `pslverr`=0 | ≤2 cycles after `penable` |

### 1.6 Clocks and Frequencies

Clock definitions live in `clocks.json` (the sole numeric + relationship source;
`constraints/<TOP>.{sdc,sgdc}` are generated from it). Here: domain count, CDC posture, reset
scheme, release-ordering constraints.
```

## top-io.json (§1.4.1's machine half)

Authored by Wave 1; schema `references/top-io.schema.json`. A JSON array, one object per port.

| Field | Rule |
|---|---|
| `name` | Required. The netlist name **including its bit range** (`token_in[4:0]`) — emitted verbatim into `get_ports` / `abstract_port`. |
| `direction` | Required: `input` / `output` / `inout`. |
| `width` | Required **integer**. When `name` ends in `[h:l]`, the two must agree — checked when the file is read; an `[i]` index (a register-file element) makes no width claim and is skipped. |
| `clock_domain` | Required. A `clocks.json` name. Clock and reset ports carry no IO delay; each `data` port gets `set_input/output_delay` against this domain. |
| `interface_group` | Required. Groups ports into one TB agent / one vif. |
| `role` | Required: `clock` / `reset` / `data`. `derive-constraints` branches on it. |
| `reset_polarity` / `reset_kind` | **Required when `role` is `reset`** (schema-enforced): `0` = active-low / `1` = active-high; `sync` / `async`. |
| `protocol` | Optional. |
| `encoding` | A **control or status** port MUST pin its bit/field-to-symbol meaning: single-bit `0:<meaning>; 1:<meaning>`; multi-bit per field `bit[h:l] <name>: <code>:<symbol>; …`. For a phase/command code write the **consumer obligation**, not just a label (e.g. `3:PV (consumer re-preloads the stationary operand, then streams)`). A raw data / clock / reset port has none. Enforced by the spec-review `conformance` lens, NOT a deterministic gate. This entry is the single source — a child names the port, never re-describes the codes. |

## interconnects.json (§1.4.2's machine half)

Authored by Wave 1; schema `references/interconnects.schema.json`. A JSON array, one object
per cut edge. An N=1 module writes `[]`.

| Field | Rule |
|---|---|
| `wire` | Required. Not unique by itself: the same net may appear once per distinct endpoint pairing. |
| `producers` / `consumers` | Required **arrays** of RTL module names. `const` marks a literal source with no owning module. `derive-ports` attributes each wire to the children whose `rtl_modules` appear here. |
| `width` | Required integer. A heterogeneous control bundle cannot state one honest width — split it into per-field wires. |
| `clock_domain` | Required. A `clocks.json` name; a phantom domain here hides a CDC path. |
| `protocol` / `timing_constraint` / `notes` | Optional. |
| `encoding` | A wire carrying an **encoded control/status value** MUST pin its bit/field-to-symbol meaning, same format and obligation rule as `top-io.json`. Producer and consumer read this one entry, so per-wire agreement is structural. Cross-**bus** consistency is not pinned here — that joint contract goes in the §1.4.2.1 companion. |

## features.json (§1.3's machine half)

Authored by Wave 1; schema `references/features.schema.json`. A JSON array, one object per
feature. All fields are free prose — no script parses inside a field.

| Field | Rule |
|---|---|
| `id` | Required. What `check-hints/<child>.json` `source_feature` values and testpoints refer to. |
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
  { "name": "clk",    "period_ns": 10.0, "relationship": "primary", "generated": false, "role": "primary clock" },
  { "name": "clk_io", "period_ns": 20.0, "relationship": "async",   "generated": false, "role": "IO-domain clock" }
]
```

| Field | Rule |
|---|---|
| `name` | Required. For a non-generated clock this is also the top-level port name `create_clock` binds to. |
| `period_ns` | Required **number** (not a string). The sole statement of the clock's rate — nothing records the frequency separately, so nothing can disagree with it. |
| `relationship` | Required, one of `primary` / `synchronous-related` / `async`. `async` drives `set_clock_groups -asynchronous` (SDC) and a distinct `-domain` (SGDC). **Exactly one `primary`** — it is the TB main clock; `derive-constraints` fails loud otherwise. |
| `generated` | Optional (default `false`). `true` for a divider/PLL output with no top-level port: `derive-constraints` emits **no** `create_clock` and records a `create_generated_clock`-deferred-to-RTL note in its place. |

`additionalProperties` is `false`: a mistyped key fails at write time, in front of you.

## Submodule Index Template (§1.7)

```markdown
### 1.7 Submodule Index

The child registry is `manifest.json` in this same directory — one entry per child, carrying
`name` / `doc` / `rtl_modules` / `brainstorm_anchor`.
```

Point at the manifest and write nothing else here.

For every module (N≥1) each child's detail lives in its own `<child>.md` (per
`child-design-template.md`), authored by wave-2 — which always dispatches one sub-Task per child
(N=1 → ×1, never an inlined submodule body in `design.md`).

## What the gates check

Each sidecar's own shape is its `references/*.schema.json`, field by field — read the schema, not
a summary of it; it is enforced wherever a verb reads that file. What no schema can express is a
relation *between* files, and that is `check-crossrefs`, whose verdict names each one by key.
Nothing is restated here: a third hand-written copy of the same rules is the diverged-cell problem
this template warns about everywhere else.

> Derivation rules, UVM field mapping, and a complete derivation-chain example are owned by `veripower:simulation-plan`. You do not need to read them.

## Document Control

```markdown
## 2. Document Control

| Version | Date | Notes | brainstorm.md |
|------|------|------|---------------------|
| 0.1 | YYYY-MM-DD | Initial draft | approved |
```
