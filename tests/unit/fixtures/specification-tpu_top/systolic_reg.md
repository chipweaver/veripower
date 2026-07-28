---
child: systolic_reg
parent: tpu_top
brainstorm_anchor: "lines 59-64"
ports:
  - systolic_in1
  - systolic_in2
  - mac00_in
  - mac10_in
  - i_clk
  - i_rstn
clocks:
  - { name: i_clk, domain: i_clk }
features:
  - F-02
---

# systolic_reg — Systolic Input Skew Alignment (F-02)

## 1. Purpose

`systolic_reg` is the input-skew aligner for the 2×2 weight-stationary systolic
array. The diagonal compute wavefront requires the two input streams to enter
the MAC array staggered by one cycle: column-0 data (`in1`) must arrive one
cycle ahead of column-1 data (`in2`). This child produces that stagger.

Implementation strategy (fixed by the known-good reference, reproduced exactly):
- `out1` = `in1` delayed **1** cycle, using one register `delay10`.
- `out2` = `in2` delayed **2** cycles, using two registers `delay20` → `delay21`.

In the integrated `tpu_top`, `in1`/`in2` are driven by the input FIFO read data
(`systolic_in1` = `fifo_00.o_data`, `systolic_in2` = `fifo_01.o_data`), and the
skewed outputs feed the top-row MAC `i_data` inputs (`mac00_in` =
`systolic_reg.out1` → `mac_00.i_data`; `mac10_in` = `systolic_reg.out2` →
`mac_10.i_data`). The block is purely a delay-line: no control, no
back-pressure, no handshake. Async active-low reset clears all skew registers to
0. There is no flexibility or configurability beyond the fixed 1-/2-cycle skew —
the schedule is locked to the existing directed testbench timing.

## 2. Interface

Single clock domain `i_clk`; asynchronous active-low reset `i_rstn`
(`negedge i_rstn`). Data is 32-bit throughout.

| Port (child) | Mapped net (tpu_top) | Direction | Width | Clock Domain | Protocol | Timing Semantics |
|--------------|----------------------|-----------|-------|--------------|----------|------------------|
| `in1` | `systolic_in1` (`fifo_00.o_data`) | input | 32 | i_clk | combinational | Captured on rising `i_clk` into `delay10`. |
| `in2` | `systolic_in2` (`fifo_01.o_data`) | input | 32 | i_clk | combinational | Captured on rising `i_clk` into `delay20`. |
| `out1` | `mac00_in` (→ `mac_00.i_data`) | output | 32 | i_clk | registered | `in1` delayed exactly 1 cycle (value of `delay10`). |
| `out2` | `mac10_in` (→ `mac_10.i_data`) | output | 32 | i_clk | registered | `in2` delayed exactly 2 cycles (value of `delay21`). |
| `i_clk` | `i_clk` | input | 1 | i_clk | - | Single clock; all registers update on its rising edge. |
| `i_rstn` | `i_rstn` | input | 1 | async | - | Asynchronous active-low reset; clears all skew registers. |

Note: `out1` maps to net `mac00_in` and `out2` maps to net `mac10_in`
(the nets are named for their MAC consumers, not for the producing port).

## 3. Internal Behavior

Three 32-bit delay registers form two delay lines:

- **1-cycle line (in1 → out1):** one register `delay10`. On each rising `i_clk`,
  `delay10 <= in1`; the output is `out1 = delay10`.
- **2-cycle line (in2 → out2):** two cascaded registers `delay20` → `delay21`.
  On each rising `i_clk`, `delay20 <= in2` and `delay21 <= delay20`; the output
  is `out2 = delay21`.

Reset: asynchronous, active-low (`negedge i_rstn`). When `i_rstn` is low, all
three skew registers `delay10`, `delay20`, `delay21` are cleared to 0
asynchronously (immediately, independent of `i_clk`). On reset release, normal
clocked delay operation resumes.

| Register | Updates on | Next-state | Reset value (async, `i_rstn`=0) | Drives |
|----------|-----------|-----------|----------------------------------|--------|
| `delay10` | rising `i_clk` | `in1` | 0 | `out1` (`mac00_in`) |
| `delay20` | rising `i_clk` | `in2` | 0 | `delay21` |
| `delay21` | rising `i_clk` | `delay20` | 0 | `out2` (`mac10_in`) |

Latency contract: a word presented on `in1` appears on `out1` after 1 cycle; a
word presented on `in2` appears on `out2` after 2 cycles. Consequently `out1`
leads `out2` by exactly 1 cycle for the same-cycle-presented input pair —
producing the staggered diagonal wavefront the MAC array expects.

## 4. Corner Cases

- **Reset asserted mid-stream:** if `i_rstn` is driven low while data is flowing,
  `delay10`, `delay20`, and `delay21` are cleared to 0 asynchronously
  (`negedge i_rstn`), so both `out1` and `out2` become 0 and the in-flight skew
  contents are discarded. The 1-/2-cycle latency restarts from the reset-release
  edge.
- **out1 leads out2 by 1 cycle:** for an input pair (`in1`, `in2`) presented in
  the same cycle, `out1` (1-cycle delay) emerges one cycle before `out2`
  (2-cycle delay). This stagger is the intended diagonal-wavefront alignment, not
  an error.
- **No back-pressure / no handshake:** the block always captures whatever is on
  `in1`/`in2` each clock; there is no enable, full, or empty signal. Upstream
  FIFO pop timing (driven by the parent `fifo_en`) determines which words are
  meaningful; this delay-line simply shifts them.
- **First cycles after reset release:** for the first 1 (out1) / 2 (out2) cycles
  after reset release, the outputs reflect the just-cleared 0 contents until the
  new inputs propagate through the delay registers.

## 5. Verification Hints

The check hints live in `check-hints/systolic_reg.json`.
