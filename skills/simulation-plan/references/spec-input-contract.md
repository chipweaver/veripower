# Spec Fields → Simulation-Plan Objects (plan-data.json field guide)

`derive-plan-data` extracts `design.md` §1.4.1 / §1.4.2 into `plan-data.json` and aggregates
every `check-hints/<child>.json` into `check_hints[]`. Clocks, features and timing scenarios
never pass through it: they are authored as `clocks.json` / `features.json` /
`timing-scenarios.json` and read from there directly. You author the scaffold and
`verification-plan.md` **from that JSON**; do not re-read `design.md` / `<child>.md` into
the main thread. This guide names the `design.md` columns only so you recognize where each
`plan-data.json` field came from, and maps them to the objects this stage authors
(`scaffold-specification.json`: `agents` / `sequences` / `tests` / `testpoints[]` /
`power_scenarios[]`, and `verification-plan.md`). It does not gate completeness: design-template's
gate table plus `check-coverage` enforce that upstream, before this stage runs.

**Scope boundary.** This guide stops at the JSON contract you author. Turning the scaffold into
SystemVerilog (driver / monitor bodies, RM `predict()`, scoreboard `check_txn`, reset) happens
later in the `simulation` stage (`skills/simulation/references/inlined-check-hints.md`). Do not
add SV-rendering claims here.

## Basic principles

- **Author from `plan-data.json`, not the raw spec.** `derive-plan-data` distils every field
  below into it; the `design.md` column names in this guide are provenance, so you recognize
  each field. Reserve any raw `design.md` read for prose the extract omits (§1.1–1.2 overview),
  and keep it bounded.
- **The single human source of truth is `design.md`.** There is no separate
  requirement-to-testpoint mapping document.
- Structured fields must live in `features.json` / `clocks.json` or in fixed design.md
  sections (§1.4.1 / §1.4.2) or in an authored sidecar; they must not be scattered across
  free-form prose.
- `features.json` requires every field but `coverage_intent`, so a degraded feature list is
  not a case you have to cope with — an incomplete one fails the specification gate.
- Per-child `<child>.md` sections carry implementation constraints: register side effects,
  exceptions, concurrency, back-pressure, reset, state-machine boundaries.

---

## features.json (drives testcase decomposition)

| Field | Use |
|---|---|
| `id` | Unique requirement / feature identifier, e.g., `F-00`. |
| `name` | Human-readable feature name. |
| `description` | Summary of feature scope, behavior, and constraints. |
| `mode_interface` | Points to the interface, mode, or scenario domain. |
| `priority` | Your authoring-priority signal (which behaviors to cover first). Not consumed by any script. |
| `happy_path` | Main positive path; the happy-path testcase you author. |
| `corner_cases` | Boundary / concurrency / timing / back-pressure cases you author. |
| `negative_cases` | Exceptions, illegal inputs, non-target capabilities you author as negative cases. |
| `coverage_intent` | Optional. Expected coverage model, e.g., registers, modes, error codes, cross coverage. |

Example:

```json
[
  {
    "id": "F-00",
    "name": "APB slave interface",
    "description": "Supports APB3 single-beat access with wait cycles",
    "mode_interface": "APB",
    "priority": "smoke",
    "happy_path": "Legal R/W transactions complete",
    "corner_cases": "pready inserts wait cycles",
    "negative_cases": "Illegal address access",
    "coverage_intent": "R/W, wait, error-response coverage"
  }
]
```

`happy_path` / `corner_cases` / `negative_cases` give you the positive / boundary / negative
testcases and testpoints to author.

---

## Overview §1.4 Interface tables (§1.4.1 drives transactions / agents; §1.4.2 aware-only)

### §1.4.1 Top-Level IO table (DUT boundary, primary derivation input)

| Column | What you do with it |
|---|---|
| `Signal name` | Fills `interface.signals[].name` (the vif port); materialize fills this, do not hand-transcribe. |
| `Width` | Fills `interface.signals[].width` and `transaction.fields[].width`; materialize fills this. |
| `Interface group` | The agent grouping key: signals sharing a group become one vif + one agent. |
| `Role` | `clock` / `reset` / `data`. clk/rst signals are excluded from `transaction.fields` and bound via `primary_clock` / `reset`; a data row needs `Role=data`. Gated: an empty Role fails loud. |
| `Direction` | `input` / `output` (DUT view). Gated: materialize requires it non-empty on data signals. Use it to set each agent's `mode` (`active` for a group you drive, `passive` for one you only observe); the value is not otherwise script-consumed. |
| `Clock domain` | Informational; recorded in plan-data but not consumed. Agent grouping is by `Interface group`, not clock domain. |
| `Protocol` | Your reference for the sequence pattern to author (e.g. `APB3` / `AXI4` / `custom`); not script-consumed. |

**Mapping rules:**
- Signals in the same `Interface group` become one virtual interface + the corresponding agent.
- clk/rst signals carry no `Interface group`: they bind via `primary_clock` / `reset`, not as
  agent signals. Putting them in a group collides with the clk/rst port name at render time.
- `transaction.fields` are the group's signals minus clk/rst, named verbatim after the signal;
  materialize does not abstract, rename, or merge them.

**Note:** §1.4.1 also carries `ResetPolarity` / `ResetKind`; these are consumed by constraint
generation (the `derive-constraints` verb), **not** by you.

### §1.4.2 Inter-module Interconnects table (cross-child wires, aware-only)

Lists wires between RTL modules inside the DUT (Producer / Consumer at the RTL-module level /
Protocol / Timing). Simulation is **aware-only** of this table: cross-module wires are NOT part
of the DUT transaction class and do NOT add agents. The table is consulted for monitor placement
hints (internal bus snooping for debug coverage) and for understanding back-pressure paths that
surface at the DUT boundary.

In fan-out mode each cross-child wire is declared once here; per-child `<child>.md §2 Interface`
references but does not redefine it.

---

## timing-scenarios.json (drives sequence authoring)

| Field | What you do with it |
|---|---|
| `id` | Author one sequence in `sequences[]` per scenario (e.g. `SC-APB-00`). |
| `interface_mode` | Which agent receives the stimulus (the §1.4 interface group). |
| `stimulus` | The sequence body (concrete stimulus steps). |
| `expected` | The testpoint check intent (the DUT-observable output the downstream scoreboard will judge). |
| `timing_constraint` | Recorded in the testpoint intent (e.g. "pready high within ≤2 cycles after penable"). |
| `exceptions` | A negative-path sequence + a negative testpoint. |

design.md §1.5 still holds the waveform diagrams and their phase-by-phase descriptions; read
them for the cycle-level detail a scenario row cannot carry.

**Mapping rules:**
- Each `id`: author one sequence class in `sequences[]`.
- `expected` + `timing_constraint`: record as the testpoint's check intent; the downstream
  `simulation` stage renders the actual scoreboard check from it.
- `exceptions`: author a negative sequence + a negative testpoint.

---

## Per-child `check-hints/<child>.json` (drives inlined_check_hints[])

The check hints live in `check-hints/<child>.json` (one per child unit declared
in `manifest.json`). You cluster its rows into `testpoints[].covers[]`; materialize then fills
each `testpoints[].inlined_check_hints[]` from those `covers[]`.

| Column | Where it lands |
|---|---|
| `check_id` | Identifies the check; you cluster it into a testpoint via `covers[]`. |
| `source_feature` | Traces back to a `features.json` `id`. |
| `implementation_detail` | ≤20-word constraint summary; the fallback source for `inlined_check_hints[].implementation_detail`. |
| `implementation_detail_verbatim` | Verbatim cycle-accurate formula; the **preferred** source, materialized into `inlined_check_hints[].implementation_detail`. |
| `observable` | Copied to `inlined_check_hints[].observable` (metadata for the downstream check author). |
| `reference_rule` | Copied to `inlined_check_hints[].reference_rule` (metadata for the downstream check author). |
| `latency` | Copied to `inlined_check_hints[].latency` (metadata). |
| `reset_behavior` | Copied to `inlined_check_hints[].reset_behavior` (metadata). |

`materialize-scaffold` fills `inlined_check_hints[]` deterministically from your `covers[]` +
plan-data: `implementation_detail = verbatim-if-present-else-summary`, and the other four columns
copied as metadata. How those hints become SV `predict()` / scoreboard checks is the downstream
`simulation` stage's job.

---

## Spec field → scaffold object index

Section anchors in `design.md` are English canonical:
- `features.json` (NOT a design.md section) → testpoint feature IDs, test names, and the
  `name` the case-results summary prints
- §1.4.1 Top-Level IO → DUT-boundary interfaces / agents / transaction fields
- §1.4.2 Inter-module Interconnects → optional cross-module wire awareness (aware-only)
- `timing-scenarios.json` (NOT a design.md section) → scenario-driven sequences
- `clocks.json` (NOT a design.md section) → `primary_clock`, script-injected by
  `materialize-scaffold` from the single `relationship: "primary"` entry
- §1.7 Submodule Index → pointer to `manifest.json`

Per-child check hints live in `check-hints/<child>.json`; `simplan derive-plan-data --workdir`
reads `manifest.json` + each of those files and tags every hint with a `child` field.

---

## Derivation rules

- Derive `verification-plan.md` (human-readable review anchor) and `scaffold-specification.json`
  (machine-read contract) from the fields above.
- `features.json` alone gives you feature-traceability testpoints; transactions / agents /
  sequences / checks need `timing-scenarios.json`, `check-hints/*.json` and the §1.4 fields. There is no automatic generation; you
  author these, guided by the fields above.
- Non-target capabilities ("does not support" / "does not include") belong in a feature's
  `negative_cases`, so negative tests and result summaries can be derived from them.

---

## Complete derivation-chain example: APB slave register module

(These tables show the `design.md` rows as they arrive in `plan-data.json`; you read them from
that JSON, not the raw file.)

### §1.4.1 Top-Level IO table (APB slave)

```markdown
| Signal name | Direction | Width | Clock domain | Interface group | Protocol | Role |
|-------------|-----------|-------|--------------|-----------------|----------|------|
| pclk | input | 1 | pclk | | APB3 | clock |
| preset_n | input | 1 | pclk | | APB3 | reset |
| psel | input | 1 | pclk | APB | APB3 | data |
| penable | input | 1 | pclk | APB | APB3 | data |
| pwrite | input | 1 | pclk | APB | APB3 | data |
| paddr | input | 8 | pclk | APB | APB3 | data |
| pwdata | input | 32 | pclk | APB | APB3 | data |
| prdata | output | 32 | pclk | APB | APB3 | data |
| pready | output | 1 | pclk | APB | APB3 | data |
| pslverr | output | 1 | pclk | APB | APB3 | data |
```

(clk/rst carry no `Interface group`: `primary_clock` comes from `clocks.json` and `reset` from
the `Role=reset` row; grouping them under `APB` would collide with the clk/rst port name at render.)

**What this yields:**
- `apb_agent` (`mode: active`, covers Interface group `APB`).
- `apb_if.interface.signals`: `psel, penable, pwrite, paddr, pwdata, prdata, pready, pslverr`
  (all APB-group signals; `pclk` / `preset_n` are not agent signals).
- `apb_txn.transaction.fields`: the same signals, clk/rst already excluded, named verbatim:
  `psel(1), penable(1), pwrite(1), paddr(8), pwdata(32), prdata(32), pready(1), pslverr(1)`.
  materialize fills these; it does not abstract or rename (there is no `addr` / `data` / `rw`).

### timing-scenarios.json (APB slave)

```json
[
  {
    "id": "SC-APB-00",
    "interface_mode": "APB / write",
    "stimulus": "Legal-address write transaction",
    "expected": "pready high within 1-2 cycles, pslverr=0",
    "timing_constraint": "<=2 cycles after penable"
  },
  {
    "id": "SC-APB-02",
    "interface_mode": "APB / write",
    "stimulus": "Illegal address (out of valid range)",
    "expected": "pslverr high; prdata don't-care",
    "timing_constraint": "<=2 cycles after penable",
    "exceptions": "Address out of range"
  }
]
```

**What you author:** `sequences[]` entries `apb_write_seq` (SC-APB-00), `apb_read_seq`
(SC-APB-01), `apb_illegal_addr_seq` (SC-APB-02), each with a testpoint recording the Expected +
Timing as its check intent.

### `check-hints/<child>.json` (APB slave)

```json
[
  {
    "check_id": "CHK-APB-00",
    "source_feature": "F-00",
    "implementation_detail": "pready single-beat by default; wait cycles may be inserted",
    "implementation_detail_verbatim": "reg_file[addr] <= pwdata (write); prdata <= reg_file[addr] (read)",
    "brainstorm_anchor": "L42",
    "observable": "pready, pslverr",
    "reference_rule": "write->reg_file[addr]=wdata; read->prdata=reg_file[addr]",
    "latency": "<=2 cycles",
    "reset_behavior": "reg_file all-zero"
  },
  {
    "check_id": "CHK-APB-01",
    "source_feature": "F-00",
    "implementation_detail": "Illegal address returns pslverr=1",
    "implementation_detail_verbatim": "pslverr <= (addr not in legal_range)",
    "brainstorm_anchor": "L57",
    "observable": "pslverr",
    "reference_rule": "addr outside legal range -> pslverr=1",
    "latency": "<=2 cycles",
    "reset_behavior": "pslverr=0"
  }
]
```

**What you author:** testpoints clustering `CHK-APB-00` / `CHK-APB-01` via `covers[]`. materialize
then fills their `inlined_check_hints[]`: `implementation_detail` from `implementation_detail_verbatim`
(`reg_file[addr] <= pwdata …`), plus `observable` / `reference_rule` / `latency` /
`reset_behavior` as metadata. The RM `predict()` and scoreboard that consume these hints are
authored downstream in the `simulation` stage.
