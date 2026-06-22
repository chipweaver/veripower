# design.md Section Template

`{workdir}/design.md` is the **sole design source of truth** produced by this skill: overview sections 1.1–1.6 describe the module as a whole (function, interfaces, timing, frequencies, architecture partitioning); submodule sections 1.7+ describe the implementation details of each submodule. All external consumers (RTL implementation / constraint generation / verification derivation / synthesis / power / timing signoff, etc.) read from this single document — there is no second copy.

> **`design.md` self-containment principle**: all critical invariants from brainstorm (RTL formulas / interface timing / numeric parameters / implementation constraints / overlay explicit spec supplement sections) must be inlined verbatim into `design.md`. **By-reference jumps are forbidden** (such as "see brainstorm §sd_clock_divider IO Ports" / "see spec D2" / "refer to brainstorm section sd_controller_wb" / "see brainstorm §X"). The downstream skill input lists do not literally include `brainstorm.md`; by-reference = information loss, which causes false-fail under cycle-accurate `===` checks. Enforced by `check_coverage.py:self_containment`.

## Document Position

| Section range | Responsibility |
|---|---|
| 1.1–1.6 Overview sections | Function, interfaces, timing, frequencies, architecture partitioning; 1:1 consistent with each D-dimension field in brainstorm.md; on conflict, this section is the single upper-layer authority. |
| 1.7+ Submodule sections | Implementation details (FIFO / arbitration / exceptions / state-machine boundaries / register side effects, etc.); on conflict, **modify the overview sections first, then the submodule sections** (`constraints/<TOP>.{sdc,sgdc}` is regenerated from §1.6 by `derive_constraints.py` — never hand-edited). |
| 2 Document control | Version, revision notes, the corresponding (frozen / approved) brainstorm.md. |

## Rendering Conventions

| Content type | Recommended format | Notes |
|----------|----------|------|
| Architecture diagrams (§1.2 / submodules §1.7+ / brainstorm D4 candidates) | mermaid code block | GitHub / VSCode preview / mkdocs all render natively; for multiple side-by-side candidates use one code block each. |
| Timing diagrams (§1.5 interface timing / brainstorm D5 scenarios) | Hand-drawn ASCII (preferred) or wavedrom | wavedrom does **not** render on GitHub — if wavedrom is used, attach an ASCII equivalent or export a PNG when reviewing the PR; otherwise stick with ASCII. |

Each timing diagram must be paired with a textual description that **maps one-to-one onto each phase of the waveform** (setup/hold, handshake meaning, typical/boundary cycles, etc.). This convention applies to both `brainstorm.md` and `design.md`.

## Overview Section Template (1.1–1.6)

```markdown
# <module_name> Design Document (design.md)

## 1. Module Overview

### 1.1 Overview
(Module description: role in the system, core problem solved, scope boundaries.)

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

The columns of the table below must satisfy the "minimum field completeness" requirements; missing columns directly break downstream auto-derivation tooling:

| ID | Feature | Description | Mode/Interface | Priority | HappyPath | CornerCases | NegativeCases | CoverageIntent |
|----|------|------|----------------|----------|-----------|-------------|---------------|----------------|
| F-00 | … | … | … | smoke | … | … | … | … |

### 1.4 Module Interface and Interconnects

#### 1.4.1 Top-Level IO

| Signal | Direction | Width | Clock Domain | Interface Group | Protocol | Role | ResetPolarity | ResetKind |
|--------|-----------|-------|--------------|-----------------|----------|------|---------------|-----------|
| clk    | input  | 1 | clk | clk     | -    | clock | -  | -     |
| rst_n  | input  | 1 | clk | reset   | -    | reset | 0  | async |
| cfg_addr | input | 8 | clk | cfg_bus | APB3 | data  | -  | -     |

> **Role** (required — `derive_constraints.py` reads it): `clock` / `reset` / `data`.
> **ResetPolarity** (reset rows only): `0` = active-low, `1` = active-high.
> **ResetKind** (reset rows only): `sync` / `async`.
> Clock and reset ports carry no IO delay; each `data` port gets
> `set_input/output_delay -clock <Clock Domain>` and an `abstract_port -clock <Clock Domain>`.
> These columns make constraint generation a pure function of this table — no name heuristics.

#### 1.4.2 Inter-module Interconnects

> Fan-out mode (N≥2): authoritative list of all RTL-module-to-RTL-module wires. N=1 modules: this table is empty + a single row with `(none — N=1 module has no inter-module wires)` or omit the table entirely.

| Wire | Producer (RTL module) | Consumer (RTL module) | Width | Clock Domain | Protocol | Timing Constraint | Notes |
|------|-----------------------|-----------------------|-------|--------------|----------|-------------------|-------|
| … | … | … | … | … | … | … | … |

> **Width** and **Clock Domain** are **gated**: every inter-module wire pins a concrete Width (`-` is not valid) and a Clock Domain that is a §1.6 clock name. (Direction is encoded by Producer/Consumer. ResetPolarity/ResetKind are NOT gated on §1.4.2 — reset is enforced only at constraint generation on §1.4.1 `Role=reset` rows.) A heterogeneous control bundle (fields of differing width, e.g. an old `ctrl_bus`) cannot fill one honest Width row — break it into per-field wires. Enforced by `check_coverage.py:structure.interconnect_violations`.

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

| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Generated | Role |
|------------|-------------------------|-----------------|--------------|-----------|------|
| clk    | 100 | 10.0 | primary | no | primary clock |
| clk_io | 50  | 20.0 | async   | no | IO-domain clock |

> **SDC Period (ns)** must equal `1000 / Nominal Frequency (MHz)` (enforced by
> `check_coverage.py` R-B). **Relationship**: `primary` / `synchronous-related` / `async`
> — `async` clocks drive `set_clock_groups -asynchronous`. **Generated**: `yes` for a
> divider/PLL output (no top-level port) — `derive_constraints.py` emits **no**
> `create_clock` for it and records a `create_generated_clock`-deferred-to-RTL note in the
> SDC header; default `no`. This table is the sole numeric + relationship source for the
> generated `constraints/<TOP>.{sdc,sgdc}`.
```

## Submodule Index Template (§1.7)

```markdown
### 1.7 Submodule Index

See `manifest.json` for the authoritative child registry. This table lists child names + brainstorm anchors as a quick reference (concrete content lives in per-child `<child>.md` files; see `child-design-template.md`).

| child name | doc | brainstorm_anchor | role |
|------------|-----|-------------------|------|
| sub_a | `sub_a.md` | brainstorm §sub_a | … |
| sub_b | `sub_b.md` | brainstorm §sub_b | … |
```

For every module (N≥1) the parent `design.md` keeps only this §1.7 index; each child's detail lives in its own `<child>.md` (per `child-design-template.md`), authored by wave-2 — which always dispatches one sub-Task per child (N=1 → ×1, never an inlined submodule body in `design.md`).

## Minimum Field Completeness Gate Table

Before `design.md` is approved, the **gated** checks below must pass `check_coverage.py:structure`; **recommended** columns degrade downstream quality if absent (`derive_plan_data` defaults them, so a missing column yields an empty/weaker derivation, not a crash). Failing any gated check disqualifies this skill from marking pass.

| Check | Field location | Impact of missing |
|--------|----------|----------|
| §1.3 columns ID / Feature / Description / Mode/Interface / Priority / HappyPath / CornerCases / NegativeCases — **(gated)** | Overview §1.3 table | Absent columns degrade downstream derivation quality; `derive_plan_data` defaults them to empty, weakening testcase decomposition and suite splitting. |
| §1.3 column CoverageIntent — **(recommended)** | Overview §1.3 table | Absent column degrades coverage-goal derivation; `derive_plan_data` defaults it to empty. |
| §1.4.1 columns Signal / Direction / Clock Domain / Interface Group / Role — **(gated)** | Overview §1.4.1 table | Absent columns degrade constraint and agent generation; `derive_constraints.py` may emit incomplete IO delays or miss CDC domains. |
| §1.4.1 columns Width / Protocol — **(recommended)** | Overview §1.4.1 table | Absent Width defaults to `1`; absent Protocol yields empty protocol annotations. |
| §1.4.1 columns ResetPolarity / ResetKind — **required on `Role=reset` rows** (enforced at constraint generation by `derive_constraints.py`, which fail-louds on a reset row missing them — not by the coverage gate; use `-` on non-reset rows) | Overview §1.4.1 table | A reset row missing polarity/kind aborts `derive_constraints.py`. |
| §1.5 columns ScenarioID / Trigger/Stimulus / Expected Result / Timing Constraint — **(gated)** | Overview §1.5 table | Absent columns degrade sequence-body and checker generation; `derive_plan_data` defaults them to empty. |
| §1.5 column Exceptions / Negative Cases — **(recommended)** | Overview §1.5 table | Absent column degrades negative-case coverage; `derive_plan_data` defaults it to empty. |
| §1.6 columns Clock Name / Nominal Frequency (MHz) / SDC Period (ns) / Relationship — **(gated)** | Overview §1.6 table | Absent columns degrade constraint generation; `derive_constraints.py` requires clock name, period, and relationship. |
| §1.6 column Generated — **(recommended)** (defaults to `"no"`) | Overview §1.6 table | Absent column causes `derive_constraints.py` to treat all clocks as top-level ports (may emit spurious `create_clock` for PLL outputs). |
| §1.6 internal consistency: `SDC Period (ns)` ≈ `1000 / Nominal Frequency (MHz)` per row — **(gated)** | Overview §1.6 table | A freq/period typo would propagate into every generated `create_clock`; enforced by `check_coverage.py` (R-B). |
| §1.4.1 `Clock Domain` values ⊆ §1.6 clock names — **(gated)** | §1.4.1 + §1.6 tables | A phantom domain would make `abstract_port -clock <phantom>` and break SpyGlass CDC; enforced by `check_coverage.py` (R-F). |
| §1.4.2 columns Width / Clock Domain present + per-row concrete — **(gated)** | Overview §1.4.2 table | Unpinned inter-module width lets body-blind fan-out children diverge (the fa_core 128b↔32b / opaque-`ctrl_bus` class); enforced by `check_coverage.py:structure.interconnect_violations`. |
| §1.4.2 `Clock Domain` values ⊆ §1.6 clock names — **(gated)** | §1.4.2 + §1.6 tables | A phantom interconnect domain hides a CDC path; enforced by `check_coverage.py:structure.interconnect_violations`. |
| Every §1.3 feature `ID` referenced by ≥1 child §5 `SourceFeature` — **(gated)** | §1.3 feature table + per-child `<child>.md §5` | Catches specified-but-unverified features; enforced by `check_coverage.py` (R-C, feature→§5 coverage). |
| `<child>.md §5` Verification-Hints table has the **gated** columns CheckID / SourceFeature / ImplementationDetail / Observable / ReferenceRule (Latency / ResetBehavior recommended; ImplementationDetailVerbatim is guarded by token-survival, BrainstormAnchor is traceability) | per-child `<child>.md §5` (see `child-design-template.md`) | Cannot generate rule-based RM / scoreboard; **enforced by `check_coverage.py` structure + R-C feature-coverage**. |
| `design.md` self-containment (no `see brainstorm` / `refer to brainstorm` / `see spec D` / cross-child links) | Whole document + each `<child>.md` | See the self-containment principle stated once above; **enforced by `check_coverage.py:self_containment`**. |

> Derivation rules, UVM field mapping, and a complete derivation-chain example are owned by `veripower:simulation-plan`. This skill does not need to read them; it only needs to ensure every check in this table lands in the table columns.

## Document Control

```markdown
## 2. Document Control

| Version | Date | Notes | brainstorm.md |
|------|------|------|---------------------|
| 0.1 | YYYY-MM-DD | Initial draft (overview + submodules full) | approved |
```

`brainstorm.md` is **frozen** for the duration of a run: design.md derives from it but never amends it in-pipeline. A requirements change is handled out-of-band, not by editing brainstorm.md mid-flow.

## Fidelity (objective gate — no self-certification section)

`design.md` carries **no** §3 Derivation Notes or §4 Internal Consistency Self-Check
table. Fidelity is verified objectively by `check_coverage.py`, which writes
`{workdir}/coverage.json`:

- `token_survival` — every hard token in the **whole** brainstorm (a fenced code block /
  `assign …;` / `always @(…) …;` / `parameter`/`localparam` numeric def / sized literals
  `N'hXX` / timing `N.N ns`) must survive as a **contiguous** substring in `design.md ∪ <child>.md`.
- `brainstorm_coverage` — every brainstorm chapter (ATX ≤ 2, minus `shared_subsections`)
  falls in some child's `brainstorm_anchor` range. Reports `gaps` + `orphans` only.
- `frontmatter_subset` — child `ports / clocks / features` ⊆ the main design tables.
- `self_containment` — no by-reference jumps to brainstorm; no cross-child `<child>.md` links.
- `structure` — §1.4.x present; §1.3/§1.4.1/§1.5/§1.6 + child §5 gated columns; §1.6 freq↔period
  (R-B); §1.4.1 Clock-Domain ⊆ §1.6 (R-F); every §1.3 feature covered by a child §5 (R-C).

The brainstorm → design.md handoff is **frozen** (see Document Control). The machine
checks token survival + coverage (substring/structural); a human reviewer judges
engineering soundness — the semantic "not contradictory" consistency the token check
cannot catch.
