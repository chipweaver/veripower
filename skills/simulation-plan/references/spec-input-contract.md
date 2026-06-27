# Spec → Simulation Input Contract (consumer-side copy)

This document describes how the `simulation-plan` / `simulation` stages derive testpoints, UVM transactions, agents, sequences, checkers, and rule-based reference models from `Design/specification/design.md`. **Spec authors do not need to read this.** They only need to satisfy the "Minimum Field Completeness Gate Table" in `${CLAUDE_PLUGIN_ROOT}/skills/specification/references/design-template.md`. This file is the consumer-side contract copy that reverse-anchors the fields spec must provide.

## Basic principles

- **The single human source of truth is `design.md`.** There is no separate requirement-to-testpoint mapping document.
- Structured fields must live in fixed sections (§1.3 / §1.4.1 / §1.4.2 / §1.5 / per-child `<child>.md §5` verification-hint tables); they must not be scattered across free-form prose.
- The minimum compatible input is the three columns `ID` / `Feature` / `Description` in §1.3. The more complete the fields, the higher the quality of automated derivation.
- Per-child `<child>.md` submodule sections carry implementation-related constraints, especially register side effects, exceptions, concurrency, back-pressure, reset, and state-machine boundaries.
- **Before `specification` is set to `pass`, the fields must be sufficient to support automated derivation of transactions / agents / seqs / checkers / rule-based RMs.** When fields are missing, `simulation-plan` writes `result.json` with `status=fail` and `stage_specific.fail_reason` describing the gap; the caller decides next steps from there, instead of pressing on.

---

## Overview §1.3 Main Features table (drives testcase decomposition)

| Column | Required | Use |
|---|---|---|
| `ID` | required | Unique requirement / feature identifier, e.g., `F-00`. |
| `Feature` | required | Human-readable feature name. |
| `Description` | required | Summary of feature scope, behavior, and constraints. |
| `Mode/Interface` | recommended | Points to the interface, mode, or scenario domain. |
| `Priority` | recommended | Specifies `smoke` / `P0` / `regress` priority, etc. |
| `HappyPath` | recommended | Main positive-test path → drives the happy-path sequence. |
| `CornerCases` | recommended | Boundary, concurrency, timing, back-pressure scenarios → drive corner sequences. |
| `NegativeCases` | recommended | Exceptions, illegal inputs, non-target capabilities → drive negative sequences. |
| `CoverageIntent` | recommended | Expected coverage model, e.g., registers, modes, error codes, cross coverage. |

Example:

```markdown
| ID | Feature | Description | Mode/Interface | Priority | HappyPath | CornerCases | NegativeCases | CoverageIntent |
|----|---------|-------------|----------------|----------|-----------|-------------|---------------|----------------|
| F-00 | APB slave interface | Supports APB3 single-beat access with wait cycles | APB | smoke | Legal R/W transactions complete | pready inserts wait cycles | Illegal address access | R/W, wait, error-response coverage |
| F-01 | AES-128 encryption | AES-128 encryption in ECB mode | ECB | P0 | Reference vectors match | Back-to-back block input | Unsupported keylen config | mode × keylen coverage |
```

**Derivation targets:** `HappyPath` / `CornerCases` / `NegativeCases` drive testcase decomposition directly; `Priority` decides whether a testcase lands in the `smoke` or the `regress` suite.

---

## Overview §1.4 Interface tables (drives transaction / interface / agent generation)

**§1.4 split** — §1.4 is split into two subsections; only §1.4.1 drives DUT-boundary
transactions / agents. §1.4.2 is simulation-aware-only (informational; cross-module
wires are not part of the DUT transaction class).

### §1.4.1 Top-Level IO table (DUT boundary — primary derivation input)

| Column | Required | Derivation target |
|---|---|---|
| `Signal name` | required | virtual interface port name. |
| `Direction` | required | driver (DUT input) / monitor (DUT output) role assignment. |
| `Width` | required | Transaction field width; interface port width. |
| `Clock domain` | recommended | Agent grouping basis (signals in the same clock domain go in the same agent). |
| `Interface group` | recommended | Signals in the same group go in the same agent (e.g., `APB`, `AXI_W`, `IRQ`). |
| `Protocol` | recommended | Decides the sequence pattern (e.g., `APB3` / `AXI4` / `custom`). |
| `Role` | recommended (gated upstream) | `clock` / `reset` / `data` — drives clk/rst exclusion from `transaction.fields` and reset-port identification. |

**Mapping rules:**
- Signals in the same `Interface group` → one virtual interface + the corresponding agent.
- `Direction = input` (DUT view) → driver drives.
- `Direction = output` (DUT view) → monitor samples.
- `Width` → transaction class field width definition.

**Note:** §1.4.1 also carries `ResetPolarity` / `ResetKind`; these are consumed by constraint generation (the `derive-constraints` verb), **not** by `simulation-plan`.

### §1.4.2 Inter-module Interconnects table (cross-child wires — aware-only)

Lists wires between RTL modules inside the DUT (Producer / Consumer at the
RTL-module level / Protocol / Timing). Simulation is **aware-only** of this
table: cross-module wires are NOT part of the DUT transaction class and do
NOT add agents. The table is consulted for monitor placement hints (e.g.,
internal bus snooping for debug coverage) and for understanding back-pressure
paths that surface at the DUT boundary.

In fan-out mode each cross-child wire is declared once here; per-child
`<child>.md §2 Interface` references but does not redefine it.

---

## Overview §1.5 Interface Timing Scenarios table (drives sequence / checker generation)

| Column | Required | Derivation target |
|---|---|---|
| `ScenarioID` | recommended | One-to-one mapping ID for sequence and testcase (e.g., `SC-APB-00`). |
| `Interface / Mode` | recommended | Decides which agent receives the stimulus (corresponds to §1.4 interface group). |
| `Trigger / Stimulus` | recommended | Drives sequence body logic (concrete stimulus steps). |
| `Expected result` | recommended | Drives the checker decision condition (DUT-observable output). |
| `Timing constraint` | recommended | Drives the checker timing window (e.g., "pready high within ≤2 cycles after penable"). |
| `Exception / Negative` | optional | Drives negative testcase sequences (illegal input, error recovery). |

**Mapping rules:**
- Each `ScenarioID` → one sequence class.
- `Expected result` + `Timing constraint` → checker decision logic + timeout window.
- `Exception / Negative` → negative sequence + corresponding error checker.

---

## Per-child `<child>.md §5` Verification Hints table (drives RM rules / checker implementation details)

The 9-column Verification Hints table lives in each `<child>.md §5` (one per child unit
declared in `manifest.json`).

| Column | Required | Derivation target |
|---|---|---|
| `CheckID` | recommended | Unique checker-rule identifier (e.g., `CHK-APB-00`). |
| `SourceFeature` | recommended | Traces back to the §1.3 feature ID (e.g., `F-00`). |
| `ImplementationDetail` | recommended | ≤20-word summary of the implementation constraint (state-machine boundary, register side effect, clearing timing). Fallback RM source when no verbatim formula exists. |
| `ImplementationDetailVerbatim` | recommended (token-survival-guarded) | Verbatim cycle-accurate formula, present only when a formula exists; the **preferred** RM `predict()` source — materializes into scaffold `inlined_check_hints[].implementation_detail`. |
| `Observable` | recommended | Monitor-sampled signal + scoreboard compare field. |
| `ReferenceRule` | recommended | RM input-to-output mapping rule description (drives the `predict()` method logic). |
| `Latency` | optional | Expected response latency (in cycles); used by checker timeout decisions. |
| `ResetBehavior` | optional | Expected value after reset; used by reset-check checkers (drives the `reset()` method). |

Example:

```markdown
| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-APB-00 | F-00 | pready single-beat by default; wait cycles may be inserted | reg_file[addr] <= pwdata (write); prdata <= reg_file[addr] (read) | L42 | pready_o, pslverr_o | write→reg[addr]=wdata; read→prdata=reg[addr] | ≤2 cycles | reg_file all-zero |
| CHK-APB-01 | F-00 | Illegal address returns pslverr=1; prdata invalid | pslverr <= (addr ∉ legal_range) | L57 | pslverr_o | addr ∉ legal range → pslverr=1 | ≤2 cycles | pslverr=0 |
```

---

## Field-to-UVM-component mapping

```text
§1.4.1 Top-Level IO table    ──→  transaction class fields (widths from the "Width" column)
                                  + virtual interface port definitions (signal name + direction + width)
                                  + agent grouping (by "Interface group" / "Clock domain")
                                  + driver-driven signal set (Direction = input, DUT view)
                                  + monitor-sampled signal set (Direction = output, DUT view)

§1.4.2 Inter-module Interconnects ──→  simulation aware-only (no transaction class,
                                       no agent); optional internal-monitor placement
                                       hints + back-pressure path tracing.

§1.3 Main Features table     ──→  testcase decomposition + verification-plan.md §3 testpoints table
  + HappyPath        ──→  happy-path sequence intent
  + CornerCases      ──→  corner sequence intent
  + NegativeCases    ──→  negative sequence intent
  + Priority         ──→  smoke / regress suite assignment

§1.5 Timing Scenarios table  ──→  sequence class (one sequence per ScenarioID)
  + Trigger / Stimulus  ──→  sequence body logic skeleton
  + Expected result     ──→  checker decision condition
  + Timing constraint   ──→  checker timeout window (response within N cycles)
  + Exception / Negative ──→  negative sequence + error checker

§1.7 Submodule Index         ──→  pointer to `manifest.json` (children[].name + children[].doc)
                                  for per-child Verification Hints lookup.

<child>.md §5 Verification Hints  ──→  RM rule implementation + checker details + timeout / reset checks
  + ImplementationDetailVerbatim ──→  scaffold inlined_check_hints[].implementation_detail
                                      (verbatim cycle-accurate formula; the ≤20-word ImplementationDetail
                                       summary is the fallback — the summary alone is NOT the cycle-accurate source)
  + ReferenceRule    ──→  RM predict() method logic
  + Observable       ──→  monitor-sampled signal + scoreboard compare field
  + Latency          ──→  checker timeout window (cycles)
  + ResetBehavior    ──→  checker post-reset initial-value check + RM reset() method
```

---

## Spec field → simulation object derivation

Section anchors in `design.md` are English canonical (Surface 1):
- §1.3 Feature Table → testpoint feature IDs
- §1.4.1 Top-Level IO → DUT-boundary interfaces / agents / transaction fields
- §1.4.2 Inter-module Interconnects → optional cross-module wire awareness
  (simulation aware-only; cross-module wires are not part of DUT transaction class)
- §1.5 Interface Timing Scenarios → scenario-driven sequences
- §1.6 Clocks and Frequencies → clock domain, primary_clock
- §1.7 Submodule Index → pointer to `manifest.json`

Per-child Verification Hints (9-column table) live in `<child>.md §5`;
`simplan derive-plan-data --workdir` reads `manifest.json` + each `<child>.md`
and tags each hint with a `child` field.

---

## Derivation rules

- The `simulation-plan` stage derives `verification-plan.md` (human-readable review anchor, with testpoints and power-scenario sections) and `scaffold-specification.json` (machine-read contract, with `agents` / `sequences` / `tests` / `testpoints[]` / `power_scenarios[]`) from the fields above.
- When §1.3 contains only the three columns `ID` / `Feature` / `Description`, the derivation script falls back to a minimum testpoint set; it **cannot** generate transactions / agents / seqs / checkers / RMs automatically. When the §1.4.1 Top-Level IO table and the §1.5 timing-scenarios table are missing, `simulation-plan` exits with `result.json status=fail` + `stage_specific.fail_reason`; do not "stretch" to generate.
- Non-target capabilities (e.g., "does not support" / "does not include") should still appear in the §1.3 feature table so negative tests and result summaries can be derived from them.
- **Without structured verification inputs, do not enter automated environment generation.** The spec is inadequate and must be completed (more inputs gathered) before planning proceeds.

---

## Complete derivation chain example: APB slave register module

### §1.4.1 Top-Level IO table (APB slave)

```markdown
| Signal name | Direction | Width | Clock domain | Interface group | Protocol | Role |
|-------------|-----------|-------|--------------|-----------------|----------|------|
| pclk | input | 1 | pclk | APB | APB3 | clock |
| preset_n | input | 1 | pclk | APB | APB3 | reset |
| psel | input | 1 | pclk | APB | APB3 | data |
| penable | input | 1 | pclk | APB | APB3 | data |
| pwrite | input | 1 | pclk | APB | APB3 | data |
| paddr | input | 8 | pclk | APB | APB3 | data |
| pwdata | input | 32 | pclk | APB | APB3 | data |
| prdata | output | 32 | pclk | APB | APB3 | data |
| pready | output | 1 | pclk | APB | APB3 | data |
| pslverr | output | 1 | pclk | APB | APB3 | data |
```

**Derived results:**
- `apb_txn`: addr[7:0], data[31:0], rw, ready_delay, slverr.
- `apb_if`: contains all APB signal ports.
- `apb_agent`: driver drives psel / penable / paddr / pwdata / pwrite; monitor samples prdata / pready / pslverr.

### §1.5 Interface Timing Scenarios table (APB slave)

```markdown
| ScenarioID | Interface / Mode | Trigger / Stimulus | Expected result | Timing constraint | Exception / Negative |
|------------|------------------|--------------------|-----------------|-------------------|----------------------|
| SC-APB-00 | APB / write | Legal-address write transaction (psel → penable sequence) | pready high within 1–2 cycles, pslverr=0 | ≤2 cycles after penable | — |
| SC-APB-01 | APB / read | Legal-address read transaction (psel → penable sequence) | prdata returns the register value; pready high | ≤2 cycles after penable | — |
| SC-APB-02 | APB / write | Illegal address (out of valid range) | pslverr high; prdata don't-care | ≤2 cycles after penable | Address out of range |
```

**Derived results:**
- `apb_write_seq` (SC-APB-00), `apb_read_seq` (SC-APB-01), `apb_illegal_addr_seq` (SC-APB-02).
- `apb_ready_checker`: pready high within ≤2 cycles after penable.
- `apb_slverr_checker`: pslverr=1 on illegal address.

### `<child>.md §5` Verification Hints table (APB slave)

```markdown
| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-APB-00 | F-00 | pready single-beat by default; wait cycles may be inserted | reg_file[addr] <= pwdata (write); prdata <= reg_file[addr] (read) | L42 | pready, pslverr | write→reg_file[addr]=wdata; read→prdata=reg_file[addr] | ≤2 cycles | reg_file all-zero |
| CHK-APB-01 | F-00 | Illegal address returns pslverr=1 | pslverr <= (addr ∉ legal_range) | L57 | pslverr | addr ∉ legal range → pslverr=1 | ≤2 cycles | pslverr=0 |
```

**Derived results:**
- `apb_reg_rm`: predict() implements `if write: reg_file[addr]=wdata; if read: return reg_file[addr]`; reset() clears reg_file.
- `apb_scoreboard`: compares monitor-sampled prdata against the RM predict result; checks pslverr=1 on illegal address.

---

## Review suggestions

- When reviewing `design.md` §1.3, confirm: the feature table has stable IDs and basic scenario descriptions; HappyPath / Corner / Negative are present.
- When reviewing `design.md` §1.4.1, confirm: the Top-Level IO table includes direction / width / interface group (missing any blocks derivation).
- When reviewing `design.md` §1.4.2 (fan-out mode only), confirm: each cross-child wire is declared once with Producer / Consumer / Protocol / Timing; `<child>.md §2 Interface` only references — never redefines.
- When reviewing `design.md` §1.5, confirm: the timing-scenarios table includes ScenarioID / trigger / expected / timing constraint.
- When reviewing per-child `<child>.md §5` verification-hint tables, confirm: `ImplementationDetailVerbatim` (the cycle-accurate RM `predict()` formula source — preferred; the ≤20-word `ImplementationDetail` summary alone is NOT sufficient), `ReferenceRule` (RM core input), `Observable` (monitor observation point), `Latency` / `ResetBehavior` (checker boundary conditions) are present.
- Ensure the spec answers — before it is finalized — "how exactly is this feature tested," "what fields are in the transaction," "what does the checker compare," "what is the RM rule"; planning must not need to ask the user later.
