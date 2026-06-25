---
child: tpu_top
parent: tpu_top
brainstorm_anchor: "lines 82-160"
ports:
  - "mem[0]"
  - "mem[1]"
  - "mem[2]"
  - "mem[3]"
  - out1
  - out2
  - result_fifo_i_data
  - result_fifo_o_data
  - fifo_en
  - i_clk
  - i_rstn
  - in1
  - in2
  - in1_en
  - in2_en
  - start
  - o_full
  - o_empty
  - done
  - i_paddr
  - i_psel
  - i_pwrite
  - i_pwdata
  - i_penable
  - o_prdata
  - counter
clocks:
  - { name: i_clk, domain: i_clk }
features:
  - F-04
  - F-05
---

# tpu_top — Top Integration: APB Register File + Start/Counter Control + Done (F-04, F-05)

## 1. Purpose

`tpu_top` is the top-integration parent of the 2×2 systolic-array integer
matrix-multiply accelerator. It instantiates all leaf children — four MAC cells
(`mac_00`, `mac_01`, `mac_10`, `mac_11`), one skew aligner (`systolic_reg`), and
three FIFOs (`fifo_00`, `fifo_01`, `fifo_result`) — and wires them per the
inter-module interconnect table. In addition it holds **inline** (not as a
child) all glue logic: the APB-style register file (F-04, weight load + result
read-back), the `start`/counter control FSM (F-05), the counter-routed result
mux, and `done` generation.

This file owns the **chip boundary**: the entire top-level IO list (clk/reset,
data-in stream, control `start`/`counter`, status `o_full`/`o_empty`/`done`, and
the APB-style port group) is exposed and driven here. It also owns the
cut-edge nets it produces or consumes across module boundaries: the four weight
registers `mem[0]`/`mem[1]`/`mem[2]`/`mem[3]` (→ MAC `i_weight`), `out1`/`out2`
(← `mac_10.o_result` / `mac_11.o_result`), `result_fifo_i_data` (→
`fifo_result.i_data`), `result_fifo_o_data` (← `fifo_result.o_data`), and
`fifo_en` (→ `fifo_00.i_rd` / `fifo_01.i_rd`).

Implementation strategy (fixed by the known-good reference, reproduced exactly):
- The APB register file is a minimal APB-style access only (no full-APB / AXI
  compliance): a decoded write path into `mem[i_paddr]` and a combinational read
  path that returns `fifo_result.o_data`.
- The control is a single 4-bit free-running counter gated by `start`, driving a
  deterministic counter-coded schedule for FIFO pop, result push, result
  routing, and `done`. No flexibility/configurability beyond this fixed
  schedule — it is locked to the existing directed testbench timing.

## 2. Interface

Single clock domain `i_clk` (100 MHz, 10.0 ns); asynchronous active-low reset
`i_rstn` (`negedge i_rstn`). Data/weight/accumulator are 32-bit throughout.
Per the reference, the async reset applies to the MAC cells, skew registers,
FIFOs, and the counter; the APB write/register-file block is clocked-only with
**no reset**.

### 2.1 Top-Level IO (chip boundary, owned by this module)

| Signal | Group | Direction | Width | Clock Domain | Protocol | Timing Semantics |
|--------|-------|-----------|-------|--------------|----------|------------------|
| `i_clk` | clk_rst | input | 1 | i_clk | - | Single clock; all registers update on its rising edge. |
| `i_rstn` | clk_rst | input | 1 | async | - | Asynchronous active-low reset (`negedge i_rstn`); resets MACs/skew/FIFOs/counter. Not the APB regfile block. |
| `in1` | data_in | input | 32 | i_clk | - | 32-bit input data stream into `fifo_00`. |
| `in2` | data_in | input | 32 | i_clk | - | 32-bit input data stream into `fifo_01`. |
| `in1_en` | data_in | input | 1 | i_clk | - | Write enable for `fifo_00` (`fifo_00.i_wr`). |
| `in2_en` | data_in | input | 1 | i_clk | - | Write enable for `fifo_01` (`fifo_01.i_wr`). |
| `start` | ctrl | input | 1 | i_clk | - | Launches a compute pass; gates the counter (asserted → increment, deasserted → reset to 0). |
| `o_full` | status | output | 3 | i_clk | - | `{fifo_result, fifo_01, fifo_00}` full flags = `[2],[1],[0]`. |
| `o_empty` | status | output | 3 | i_clk | - | `{fifo_result, fifo_01, fifo_00}` empty flags = `[2],[1],[0]`. |
| `done` | status | output | 1 | i_clk | - | High when `counter >= 5`. |
| `i_paddr` | apb | input | 32 | i_clk | APB-style | Register address; selects `mem[i_paddr]` for write (`W00=0,W01=1,W10=2,W11=3`). |
| `i_psel` | apb | input | 1 | i_clk | APB-style | APB select. |
| `i_pwrite` | apb | input | 1 | i_clk | APB-style | 1 = write, 0 = read. |
| `i_pwdata` | apb | input | 32 | i_clk | APB-style | Write data into `mem[i_paddr]` on `write_enb`. |
| `i_penable` | apb | input | 1 | i_clk | APB-style | APB enable phase qualifier. |
| `o_prdata` | apb | output | 32 | i_clk | APB-style | Read data: `fifo_result.o_data` on `read_enb`, else 0. |
| `counter` | ctrl | output | 4 | i_clk | - | Exposed 4-bit counter; testbench leaves it unconnected. |

### 2.2 Inter-module Cut-Edge Nets (driven/consumed by this module)

| Net (child port) | Producer | Consumer | Direction (vs tpu_top) | Width | Clock Domain | Protocol | Timing Semantics |
|------------------|----------|----------|------------------------|-------|--------------|----------|------------------|
| `mem[0]` | tpu_top (parent regfile) | `mac_00.i_weight` | out | 32 | i_clk | registered | Weight `W00`; written by APB on `write_enb` at `i_paddr=0`. |
| `mem[1]` | tpu_top (parent regfile) | `mac_01.i_weight` | out | 32 | i_clk | registered | Weight `W01`; APB `i_paddr=1`. |
| `mem[2]` | tpu_top (parent regfile) | `mac_10.i_weight` | out | 32 | i_clk | registered | Weight `W10`; APB `i_paddr=2`. |
| `mem[3]` | tpu_top (parent regfile) | `mac_11.i_weight` | out | 32 | i_clk | registered | Weight `W11`; APB `i_paddr=3`. |
| `out1` | `mac_10.o_result` | tpu_top (parent result mux) | in | 32 | i_clk | registered | Result word A; routed into `fifo_result` when `counter ∈ {2,4}`. |
| `out2` | `mac_11.o_result` | tpu_top (parent result mux) | in | 32 | i_clk | registered | Result word B; routed into `fifo_result` when `counter ∈ {3,5}`. |
| `result_fifo_i_data` | tpu_top (parent result mux) | `fifo_result.i_data` | out | 32 | i_clk | combinational | Counter-routed result-FIFO write data (`out1`/`out2`/0). |
| `result_fifo_o_data` | `fifo_result.o_data` | tpu_top (parent APB read mux) | in | 32 | i_clk | combinational | Combinational result-FIFO read data → `o_prdata`. |
| `fifo_en` | tpu_top (parent FSM) | `fifo_00.i_rd`, `fifo_01.i_rd` | out | 1 | i_clk | combinational | Input-FIFO pop enable = `start & (counter < 2)`. |

Note: `result_fifo_wr` (drives `fifo_result.i_wr`), `write_enb`, and `read_enb`
(drives `fifo_result.i_rd`) are tpu_top-internal control strobes generated inline
in §3; they are not frontmatter cut-edge `ports` but are described here and in §3.

## 3. Internal Behavior

All inline logic lives in `tpu_top`. The MAC cells, skew register, and FIFOs are
instantiated children; the four weight registers, the APB decode, the counter,
the result mux, and `done` are inline.

### 3.1 APB-style Register File (F-04)

`mem[0:3]` holds the four weights. Two decoded enables drive the write and read
paths:

- **Write path (clocked, no reset):**
  `write_enb = i_psel & i_penable & i_pwrite`. On a rising `i_clk` while
  `write_enb` is high, `mem[i_paddr] <= i_pwdata`. This block is **clocked-only
  with no reset** (faithful to the reference) — `i_rstn` does **not** clear
  `mem`, so the weight registers retain their last-written value through reset.
- **Read path (combinational):**
  `read_enb = i_psel & i_penable & !i_pwrite`. When `read_enb` is high,
  `o_prdata = fifo_result.o_data` (combinational); otherwise `o_prdata = 0`. The
  result-FIFO read pointer advances on `read_enb` via `fifo_result.i_rd =
  read_enb` (the FIFO advances `rd_addr` on `i_rd & !o_empty`).

APB address map: `W00 = 0`, `W01 = 1`, `W10 = 2`, `W11 = 3` — `i_paddr` selects
which of `mem[0]`/`mem[1]`/`mem[2]`/`mem[3]` is written.

| Strobe | Combinational definition | Effect |
|--------|--------------------------|--------|
| `write_enb` | `i_psel & i_penable & i_pwrite` | `mem[i_paddr] <= i_pwdata` on rising `i_clk` (no reset) |
| `read_enb` | `i_psel & i_penable & !i_pwrite` | `o_prdata = fifo_result.o_data`; `fifo_result.i_rd = read_enb`; else `o_prdata = 0` |

### 3.2 Start/Counter Control FSM (F-05)

A single 4-bit `counter` drives the deterministic compute-pass schedule:

- **Counter:** 4-bit; **async reset → 0** (`negedge i_rstn` clears it to 0).
  While `start` is asserted, it increments each clock; when `start` is
  deasserted, it resets to 0 (synchronously, on the clock).
- **Input-FIFO pop enable:** `fifo_en = start & (counter < 2)`. This drives
  `i_rd` of both input FIFOs (`fifo_00`, `fifo_01`), popping two elements at the
  start of a pass (`counter` = 0 and 1).
- **Result-FIFO write enable:** `result_fifo_wr = (counter ∈ {2,3,4,5})`. Drives
  `fifo_result.i_wr`.
- **Result routing into the result FIFO:**
  `result_fifo_i_data = out1` when `counter ∈ {2,4}`,
  `= out2` when `counter ∈ {3,5}`, else `0`,
  where `out1 = mac_10.o_result` and `out2 = mac_11.o_result`.
- **Done:** `done = (counter >= 5)`.

| counter | `fifo_en` (`start & counter<2`) | `result_fifo_wr` (`counter∈{2,3,4,5}`) | `result_fifo_i_data` | `done` (`counter>=5`) |
|---------|--------------------------------|----------------------------------------|----------------------|------------------------|
| 0 | 1 | 0 | 0 | 0 |
| 1 | 1 | 0 | 0 | 0 |
| 2 | 0 | 1 | `out1` | 0 |
| 3 | 0 | 1 | `out2` | 0 |
| 4 | 0 | 1 | `out1` | 0 |
| 5 | 0 | 1 | `out2` | 1 |

(`fifo_en` additionally requires `start`; the table assumes `start` asserted for
`counter` 0/1.)

### 3.3 Reset Behavior

- Asynchronous active-low `i_rstn` (`negedge i_rstn`) clears the `counter` to 0,
  and (in the instantiated children) the MAC cells, skew registers, and FIFO
  memory/pointers to 0.
- The APB register-file write block (`mem[0:3]`) is **clocked-only with no
  reset** — it is intentionally not cleared by `i_rstn` (faithful to the
  reference; called out so it is not "fixed" downstream).

## 4. Corner Cases

- **Re-assert `start` with no new weights/inputs (SC-003):** because `mem` has no
  reset and the FIFO/pipeline retain contents, re-asserting `start` re-runs the
  counter `0→…→5` over the existing pipeline/FIFO contents and `done` rises again
  (`counter >= 5`). Four APB reads then drain the result FIFO.
- **`start` deasserted mid-pass:** when `start` drops before `counter` reaches 5,
  the counter resets to 0 on the clock and `done` does **not** assert
  (`done = (counter >= 5)` is false). No partial pass completes; the schedule
  restarts cleanly on the next `start`.
- **FIFO boundary writes/reads ignored:** per the FIFO contract, a write while
  `o_full` (or a read while `o_empty`) does not advance the pointer. Thus
  `fifo_en` pops beyond available input words, or `read_enb` reads beyond
  available result words, are ignored at the boundary — `o_prdata` still returns
  the combinational `fifo_result.o_data` (the value at the unchanged `rd_addr`).
- **`o_prdata` with no read active:** whenever `read_enb` is low, `o_prdata = 0`
  regardless of result-FIFO contents.
- **Concurrent non-APB activity leaves `mem` untouched:** `mem[i_paddr]` is
  written only on `write_enb = i_psel & i_penable & i_pwrite`; other bus activity
  does not modify the weight registers.

## 5. Verification Hints

| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-TOP-01 | F-04 | APB write decode programs mem[i_paddr] from i_pwdata, clocked no reset | `write_enb = i_psel & i_penable & i_pwrite` → `mem[i_paddr] <= i_pwdata` (clocked, **no reset** on this block — faithful to the reference) | L84 | `mem[i_paddr]` (`mem[0]`/`mem[1]`/`mem[2]`/`mem[3]`) → MAC `i_weight` | on write_enb: mem[i_paddr][t+1] == i_pwdata[t] | 1 cycle | NOT reset by `i_rstn`; clocked-only, retains last value | 
| CHK-TOP-02 | F-04 | APB read returns result-FIFO o_data combinationally, else 0; advances rd ptr | `read_enb  = i_psel & i_penable & !i_pwrite` → `o_prdata = fifo_result.o_data` (combinational); otherwise `o_prdata = 0`. The result FIFO read pointer advances on `read_enb` (`fifo_result.i_rd = read_enb`). | L86-L88 | `o_prdata`, `fifo_result.i_rd` (`result_fifo_o_data`) | read_enb=1 → o_prdata==fifo_result.o_data & i_rd advances rd_addr; read_enb=0 → o_prdata==0 | 0 cycle (comb read) | regfile block no reset; result-FIFO rd_addr=0 on async reset |
| CHK-TOP-03 | F-04 | APB address map selects weight register | APB address map: `W00 = 0`, `W01 = 1`, `W10 = 2`, `W11 = 3` | L90 | `mem[0]`, `mem[1]`, `mem[2]`, `mem[3]` | i_paddr∈{0,1,2,3} maps to mem[0..3] = W00/W01/W10/W11 | 1 cycle (write) | mem not reset (clocked-only) |
| CHK-TOP-04 | F-05 | 4-bit counter: async reset 0, increments while start, resets when start low | `counter` (4-bit): async reset → 0; while `start` asserted, increments each clock; when `start` deasserted, resets to 0 | L93-L94 | `counter` | start=1 → counter[t+1]==counter[t]+1; start=0 → counter[t+1]==0 | 1 cycle | `counter` cleared to 0 on async active-low reset (`negedge i_rstn`) |
| CHK-TOP-05 | F-05 | Input-FIFO pop enable active for first two counts while start | `fifo_en = start & (counter < 2)` (drives `i_rd` of both input FIFOs — pops two elements at the start of a pass) | L95-L96 | `fifo_en` → `fifo_00.i_rd`, `fifo_01.i_rd` | fifo_en == (start & (counter<2)); high at counter 0,1 only | 0 cycle (comb) | counter=0 on async reset → fifo_en follows start gate |
| CHK-TOP-06 | F-05 | Result-FIFO write enable active for counts 2..5 | `result_fifo_wr = (counter ∈ {2,3,4,5})` | L97 | `result_fifo_wr` → `fifo_result.i_wr` | result_fifo_wr==1 iff counter∈{2,3,4,5} | 0 cycle (comb) | counter=0 on async reset → result_fifo_wr=0 |
| CHK-TOP-07 | F-05 | Counter-routed result mux selects out1/out2/0 | `result_fifo_i_data = out1` when `counter ∈ {2,4}`, `= out2` when `counter ∈ {3,5}`, else `0`, where `out1 = mac_10.o_result` and `out2 = mac_11.o_result` | L98-L101 | `result_fifo_i_data`, `out1`, `out2` | counter∈{2,4}→out1; counter∈{3,5}→out2; else 0 | 0 cycle (comb mux) | undriven outside window → 0 |
| CHK-TOP-08 | F-05 | Done asserts when counter reaches 5 | `done = (counter >= 5)` | L102 | `done` | done == (counter >= 5) | 0 cycle (comb) | counter=0 on async reset → done=0 |
| CHK-TOP-09 | F-05 | Const seed and result chain feeding the result mux (top-row zero seed) | `32'h0` → `mac_00.i_pre_result`, `mac_01.i_pre_result`; `out1 = mac_10.o_result`; `out2 = mac_11.o_result` | L152, L155-L156 | `out1`, `out2`, `result_fifo_i_data` | top-row pre_result==32'h0; out1==mac_10.o_result; out2==mac_11.o_result | registered (MAC) | MAC results 0 on async reset |
| CHK-TOP-10 | F-05 | Re-assert start re-runs pass; start deasserted mid-pass resets counter no done | `counter` (4-bit): async reset → 0; while `start` asserted, increments each clock; when `start` deasserted, resets to 0; `done = (counter >= 5)` | L93-L94, L102 | `counter`, `done` | re-assert start → counter 0→5, done rises again; drop start mid-pass → counter→0, done==0 | per-cycle | `counter`=0 on async reset (and on start deassert) |
