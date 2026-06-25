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
| Agent | Mode | Interface groups | Drives / Observes |
|-------|------|-----------------|-------------------|
| `data_in` | active | `data_in` | drives `in1`/`in2`/`in1_en`/`in2_en` input streams into the two input FIFOs |
| `core` | active | `apb`, `ctrl`, `status` | **drives** APB master (weight load + result read) and `start`; **monitors all DUT outputs** — `o_prdata`, `counter`, `o_full`, `o_empty`, `done` |

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

## 3. Testpoints Table

| TestpointID | FeatureID | Bins | Class | Suites | Stimulus / Intent | CoverageIntent |
|-------------|-----------|------|-------|--------|-------------------|----------------|
| TP-MAC-FUNC | F-01 | mac00, mac01, mac10, mac11, data_forward | functional | T-01, T-02 | Registered MAC compute + data forwarding across all four cells; array outputs via o_prdata | All four cells produce registered MAC output + forward one cycle later |
| TP-MAC-PARTIALSUM | F-01 | seed_zero, msb_accumulate | functional | T-02 | Partial-sum chaining: top-row seed `32'h0`; MSB accumulate | Verify chained accumulation and zero-seed top row |
| TP-MAC-WRAP | F-01 | overflow_wrap | corner | T-02 | 32-bit multiply/accumulate wrap (no saturation) | Exercise overflow wrap |
| TP-MAC-UNCONNECTED | F-01 | unconnected_forward | corner | T-02 | Intentionally-unconnected mac_01/mac_11 `o_data_next` must not affect results | Confirm dangling forwards harmless |
| TP-SREG-SKEW | F-02 | delay1, delay2, wavefront_align | functional | T-03 | out1=in1 delayed 1 cycle, out2=in2 delayed 2 cycles | Verify 1/2-cycle skew alignment |
| TP-SREG-RESET | F-02 | reset_clear | corner | T-03 | Async reset clears delay10/delay20/delay21 mid-stream | Reset clearing of skew registers |
| TP-FIFO-WR | F-03 | write | functional | T-04 | Write on `i_wr & !o_full` into `mem[wr_addr]`; wr_addr advances | FIFO write path |
| TP-FIFO-RD | F-03 | read, fifo_order | functional | T-04 | Combinational read `o_data=mem[rd_addr]`; rd_addr advances; FIFO order | FIFO read path + ordering |
| TP-FIFO-FLAGS | F-03 | empty, full | functional | T-04 | RM predicts `o_empty=(wr==rd)` / `o_full=((wr+1)==rd)` per cycle; **scoreboard compares against DUT `o_full`/`o_empty` directly** | Flag generation verified by direct comparison |
| TP-FIFO-BOUNDARY | F-03 | write_full_ignored, read_empty_ignored | corner | T-04 | Write-while-full / read-while-empty ignored | Boundary-ignore semantics |
| TP-FIFO-WRAP | F-03 | ptr_wrap | corner | T-04 | Modulo-8 (3-bit) pointer wrap | Pointer wrap coverage |
| TP-FIFO-RESET | F-03 | reset_clear | corner | T-04 | Async reset clears memory and both pointers to 0 | FIFO reset behavior |
| TP-APB-WRITE | F-04 | w00, w01, w10, w11 | functional | T-05 | APB weight load to `mem[i_paddr]`; map W00=0..W11=3 | Weight load to all four addresses |
| TP-APB-READ | F-04 | read_word, no_read_zero | functional | T-05 | APB read returns next result word via `o_prdata`, advances rd ptr; `o_prdata=0` when no read | Result read-back + pointer advance |
| TP-CTRL-COUNTER | F-05 | advance, reset_on_deassert | functional | T-06 | RM predicts `counter` per cycle; **scoreboard compares against DUT `counter` output directly** | Counter advance/reset verified by direct comparison |
| TP-CTRL-FIFOEN | F-05 | pop_window | functional | T-06 | `fifo_en = start & (counter<2)` pop window drives both input FIFO i_rd | Input-FIFO pop window |
| TP-CTRL-RESULTWR | F-05 | wr_window, route_out1, route_out2 | functional | T-06 | `result_fifo_wr` counter∈{2,3,4,5}; routing out1@{2,4}, out2@{3,5}, else 0 | Result write window + routing |
| TP-CTRL-DONE | F-05 | done_assert, done_deassert | functional | T-06, T-07 | RM predicts `done=(counter>=5)` per cycle; **scoreboard compares against DUT `done` output directly** | Done assertion verified by direct comparison |

## 4. Power Scenarios Materialization

| ID | Scenario | Clock | Reset | Data | Low power | Corner | sequence_ref | Purpose |
|----|----------|-------|-------|------|-----------|--------|--------------|---------|
| S1 | Static leakage | off | asserted | none | off | SS@125C | tpu_top_idle_seq | Leakage baseline |
| S2 | Clock-tree power | on | asserted | none | off | TT@25C | tpu_top_idle_seq | CTS evaluation |
| S3a | Idle (low-power off) | on | released | no_traffic | off | TT@25C | tpu_top_idle_seq | Standby baseline |
| S3b | Idle (low-power on) | on | released | no_traffic | on | TT@25C | tpu_top_idle_seq | Standby optimization |
| S4a | Typical traffic (low-power off) | on | released | business_flow | off | TT@25C | tpu_top_traffic_seq | Typical performance |
| S4b | Typical traffic (low-power on) | on | released | business_flow | on | TT@25C | tpu_top_traffic_seq | Typical signoff |
| S5 | Peak / worst case | on | released | full_toggle | off | FF@125C | tpu_top_peak_toggle_seq | PDN / IR drop |
| S6 | DVFS switching transient | switching | released | business_flow | switching | TT@25C | tpu_top_traffic_seq | di/dt |
| S7 | High-temperature leakage | off | asserted | none | off | FF@125C | tpu_top_idle_seq | Worst leakage |

**Materialization notes**
- **Reset sequence:** `i_rstn` async active-low; asserted scenarios hold `i_rstn=0`, released scenarios deassert after the reset window.
- **business_flow (`tpu_top_traffic_seq`):** continuous APB weight loads + `in1`/`in2` input streams + repeated `start` passes at the typical rate.
- **full_toggle (`tpu_top_peak_toggle_seq`):** maximally-toggling data on all `data_in` and APB write inputs for worst-case switching.
- **no_traffic / idle (`tpu_top_idle_seq`):** `start` held low, no APB or data activity.
- **Low power / DVFS:** this module has **no** low-power controls and a **single** 100 MHz clock — `low_power_state` and the S6 `switching` clock are plan-layer corner annotations only. S3b/S4b reuse S3a/S4a stimulus; S6 reuses `tpu_top_traffic_seq`.
- **Corner annotation** is corner-agnostic at RTL; RTL-equivalent scenarios share `sequence_ref` but keep independent IDs + `corner_intent`.

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
