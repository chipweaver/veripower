---
Status: approved
---

# tpu_top Verification Plan

## 1. Scope

- **Module:** `tpu_top`
- **Top:** `tpu_top` (from `Design/specification/result.json` `stage_specific.top_module`)
- **Spec references:** `Design/specification/design.md` (§1.3 Features F-01..F-05, §1.4.1 Top-Level IO, §1.4.2 Inter-module Interconnects, §1.5 Timing Scenarios SC-001..SC-003, §1.6 Clocks) + per-child `mac.md` / `systolic_reg.md` / `fifo.md` / `tpu_top.md` §5 Verification Hints (30 check hints).
- **DUT character:** functional reproduction benchmark — a 2×2 weight-stationary MAC array with systolic input skew, three 8-entry FIFOs, an APB-style register file (weight load + result read-back; **no reset on the weight regfile — spec-faithful, so weights are X until written**), and a `start`/counter control FSM. Single 100 MHz clock (`i_clk`, 10.0 ns), async active-low reset (`i_rstn`). No PPA targets, no low-power controls.

## 2. Test Strategy

### Agents (UVM)
The roster and each agent's mode + interface groups live in `scaffold-specification.json`'s
`agents[]`. What they do: `data_in` drives the `in1`/`in2`/`in1_en`/`in2_en` input streams into the
two input FIFOs. `core` drives the APB master (weight load + result read) and `start`, and its
monitor observes **every** DUT output — `o_prdata`, `counter`, `o_full`, `o_empty`, `done`.

Clock (`i_clk`) and reset (`i_rstn`) are TB-top generated (scaffold `primary_clock` / `reset`), not part of a functional agent.

**Why `core` owns apb+ctrl+status (rev 0.2):** the scaffold scoreboard subscribes to exactly ONE observer txn (`compare_txn`), and a DUT signal may belong to only one agent's interface (no overlap). To check **all** DUT outputs against the RM — not just `o_prdata` — the single observer must carry every output. The output-bearing interface groups are `apb` (`o_prdata`), `ctrl` (`counter`), and `status` (`o_full`/`o_empty`/`done`); `apb`/`ctrl` also carry inputs that need driving, so the agent owning them is **active** (drives APB + `start`) and its monitor observes all outputs. `data_in` stays a separate active driver.

### Reference model & scoreboard (multi-observable)
- **RM (`tpu_top_rm`):** input ports = `tpu_top_data_in_txn`, `tpu_top_core_txn`. Computes the expected partial-sum-chained MAC results (`o_result <= (i_data*i_weight)+i_pre_result`, 32-bit truncate/wrap), the systolic 1/2-cycle skew, FIFO order/flags, and the counter schedule (`fifo_en = start & counter<2`; `result_fifo_wr` for counter∈{2,3,4,5}; routing `out1` at {2,4} / `out2` at {3,5}). It **predicts, per cycle and in parallel**: `o_prdata`, `done = (counter>=5)`, `counter`, and `o_full`/`o_empty`. The RM mirrors the **unreset** weight regfile faithfully (weights are 0 in the model only after an APB write; tests must load weights before reading computed results — see Test preconditions).
- **Scoreboard (`tpu_top_scoreboard`):** `compare_txn = tpu_top_core_txn` — the `core` monitor txn carries every DUT output, so the scoreboard compares **each** RM prediction against its DUT counterpart with 4-state `===`: `o_prdata`, `done`, `counter`, `o_full`, `o_empty`. Each mismatch is a `` `uvm_error `` incrementing a real fail counter.

### Sequences (9; functional + power union)
Functional: `tpu_top_apb_weight_load_seq` (core), `tpu_top_data_in_stream_seq` (data_in), `tpu_top_start_seq` (core), `tpu_top_apb_result_read_seq` (core), `tpu_top_fifo_boundary_seq` (data_in), `tpu_top_rerun_seq` (core). Power: `tpu_top_idle_seq` (core), `tpu_top_traffic_seq` (data_in), `tpu_top_peak_toggle_seq` (data_in).

### Tests (7) + preconditions
`T-01` mac smoke, `T-02` full compute, `T-03` skew alignment, `T-04` fifo, `T-05` apb regfile, `T-06` counter/ctrl, `T-07` re-run (SC-003).

**Test precondition rule (rev 0.3):** because the DUT weight regfile has no reset (weights X until written), **every test that reads computed MAC results via `apb_result_read_seq` must first run `apb_weight_load_seq`** so the read compares against a deterministic value. Applied to all result-reading tests:
- T-01, T-02, T-05, T-06: already load weights first.
- T-03: reads no results (skew only) — no precondition needed.
- **T-04** (fifo): now `[apb_weight_load, data_in_stream, fifo_boundary, start, apb_result_read]` — weight load prepended (rev 0.3).
- **T-07** (rerun, SC-003 "re-run on existing contents"): now `[apb_weight_load, data_in_stream, start, rerun, apb_result_read]` — a full first pass precedes the rerun, matching the SC-003 precondition of pre-existing weights/FIFO contents (rev 0.3).

## 3. Testpoints

The testpoints live in `scaffold-specification.json`'s `testpoints[]`. The partition follows the child boundary: MAC-array compute and partial-sum chaining, skew alignment, FIFO occupancy and flags, and the top's APB register path plus the `start`/counter control sequence. Reset behavior is a per-child testpoint rather than one module-wide one, because each child releases on its own path out of reset.

## 4. Power Scenarios

The nine scenarios live in `scaffold-specification.json`'s `power_scenarios[]`. Two notes that are not per-scenario fields: this module has no low-power control signals, so every `low_power_state` is materialized `off` and S3b/S4b differ from S3a/S4a only in `corner_intent`; and `switching` has no DVFS band to name here, so S6 reuses the idle sequence and is annotated purely by corner.

## 5. Revision Summary

**Rev 0.2 (rework round 1) — trigger: `simulation` conformance-gate trip.** Merged `apb`/`ctrl`/`status` into one active `core` observer; multi-observable RM/scoreboard now compares `o_prdata` + `done` + `counter` + `o_full` + `o_empty` (fixed unverified status observables on TP-CTRL-DONE/COUNTER, TP-FIFO-FLAGS).

**Rev 0.3 (rework round 2) — trigger: `simulation` regress failure (`failure_phase=regress`).** Full regression failed 2/7: T-04 (fifo) and T-07 (rerun) read computed MAC results via `apb_result_read_seq` without loading weights first; the DUT weight regfile has no reset (spec-faithful → weights X until written) so the MACs produced X, while the RM (correctly) modeled unwritten weights as 0 → `o_prdata` X≠0. Root cause (triage): test-composition defect, NOT an RM/RTL bug (masking X in the RM would make those reads vacuous). Fix: added the weight-load precondition —
- **T-04**: `[apb_weight_load, data_in_stream, fifo_boundary, start, apb_result_read]`.
- **T-07 (SC-003)**: `[apb_weight_load, data_in_stream, start, rerun, apb_result_read]` (full first pass before the re-run).

**Unchanged (stable anchors):** the rev-0.2 agent architecture (`data_in` + `core`), RM/scoreboard, all 18 testpoint IDs + covers/inlined_check_hints, the 9 sequences (names + agents), the 9 power scenarios, and the other 5 tests (T-01/02/03/05/06). RTL and the design spec are untouched.

## Document Control

| Version | Date | Notes | spec |
|---------|------|-------|------|
| 0.1 | 2026-06-17 | Initial first-run plan: 4 agents, 9 sequences, 7 tests, 18 testpoints, 9 power scenarios | specification pass |
| 0.2 | 2026-06-17 | Rework r1: merged apb/ctrl/status → `core` observer; multi-observable RM/scoreboard | specification pass |
| 0.3 | 2026-06-17 | Rework r2: added weight-load precondition to result-reading tests T-04 + T-07 (regress X-vs-0 fix) | specification pass |
