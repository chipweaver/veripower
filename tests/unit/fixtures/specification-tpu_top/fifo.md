---
child: fifo
parent: tpu_top
brainstorm_anchor: "lines 66-80"
ports:
  - fifo_en
  - result_fifo_i_data
  - result_fifo_o_data
  - systolic_in1
  - systolic_in2
  - in1
  - in2
  - in1_en
  - in2_en
  - o_full
  - o_empty
  - i_clk
  - i_rstn
clocks:
  - { name: i_clk, domain: i_clk }
features:
  - F-03
---

## 1. Purpose

`fifo` is an 8-entry, 32-bit, pointer-based, single-clock FIFO with a
combinational read path. It is the storage primitive of feature `F-03` and is
instantiated three times in `tpu_top`:

- `fifo_00` — input FIFO for stream 1. Written from top-level `in1` (write
  enable `in1_en`); its `o_data` drives the inter-module net `systolic_in1`
  (→ `systolic_reg.in1`); its `i_rd` is driven by the parent FSM net `fifo_en`.
- `fifo_01` — input FIFO for stream 2. Written from top-level `in2` (write
  enable `in2_en`); its `o_data` drives `systolic_in2` (→ `systolic_reg.in2`);
  its `i_rd` is driven by `fifo_en`.
- `fifo_result` — result FIFO. Written from the parent result-mux net
  `result_fifo_i_data`; its `o_data` drives `result_fifo_o_data`
  (→ parent APB read mux → `o_prdata`).

Implementation strategy: a single read/write pointer pair indexes an 8-entry
register array. Writes are synchronous and gated by `!o_full`; reads advance a
synchronous read pointer gated by `!o_empty`, while the output word is purely
combinational (`o_data = mem[rd_addr]`). Empty and full are derived from pointer
comparison, with 3-bit (modulo-8) pointer wrap. Reset is asynchronous,
active-low, clearing the memory and both pointers to 0. This reproduces the
known-good reference behavior exactly; no almost-full/almost-empty, no
parameterization, and no FWFT/registered-read variants are introduced.

The per-instance status flags compose into the top-level 3-bit status buses:
`o_full = {fifo_result, fifo_01, fifo_00}` = `[2],[1],[0]`, and `o_empty` uses
the same ordering.

## 2. Interface

The table below details the `fifo` boundary ports and how each maps to the
top-level IO (§1.4.1) and inter-module nets (§1.4.2) per instance. Generic
module-port names are `i_clk`, `i_rstn`, `i_wr`, `i_rd`, `i_data`, `o_data`,
`o_full`, `o_empty`.

| Module Port | Dir | Width | Clock Domain | Timing | fifo_00 binding | fifo_01 binding | fifo_result binding |
|-------------|-----|-------|--------------|--------|-----------------|-----------------|---------------------|
| `i_clk` | input | 1 | i_clk | clock | `i_clk` | `i_clk` | `i_clk` |
| `i_rstn` | input | 1 | i_clk (async) | async active-low (`negedge i_rstn`) | `i_rstn` | `i_rstn` | `i_rstn` |
| `i_wr` | input | 1 | i_clk | synchronous; write on `i_wr & !o_full` | `in1_en` | `in2_en` | `result_fifo_wr` (parent FSM, `counter ∈ {2,3,4,5}`) |
| `i_rd` | input | 1 | i_clk | synchronous; pop on `i_rd & !o_empty` | `fifo_en` | `fifo_en` | `read_enb` (parent APB read) |
| `i_data` | input | 32 | i_clk | sampled at write edge | `in1` | `in2` | `result_fifo_i_data` |
| `o_data` | output | 32 | i_clk | combinational (`mem[rd_addr]`) | `systolic_in1` | `systolic_in2` | `result_fifo_o_data` |
| `o_full` | output | 1 | i_clk | combinational (pointer compare) | `o_full[0]` | `o_full[1]` | `o_full[2]` |
| `o_empty` | output | 1 | i_clk | combinational (pointer compare) | `o_empty[0]` | `o_empty[1]` | `o_empty[2]` |

Notes:
- `fifo_en` (net) → `fifo_00.i_rd` and `fifo_01.i_rd` (one shared net to both
  input FIFOs). It is combinational, same-cycle on `i_clk`, value
  `start & counter<2`.
- `systolic_in1` = `fifo_00.o_data`; `systolic_in2` = `fifo_01.o_data` —
  combinational, same-cycle on `i_clk`.
- `result_fifo_i_data` = parent result mux → `fifo_result.i_data`;
  `result_fifo_o_data` = `fifo_result.o_data` → parent APB read mux → `o_prdata`
  — both combinational, same-cycle on `i_clk`.
- Top-level `o_full` / `o_empty` are 3-bit, ordering
  `{fifo_result, fifo_01, fifo_00}` = `[2],[1],[0]`.

## 3. Internal Behavior

State elements (per instance):
- `mem` — 8 entries × 32 bits, addressed by the low 3 bits of the pointers.
- `wr_addr` — write pointer (3-bit, modulo-8).
- `rd_addr` — read pointer (3-bit, modulo-8).

Behavior (single clock `i_clk`):

1. **Write:** Write on `i_wr & !o_full` → `mem[wr_addr]`; `wr_addr` advances on
   the same condition. A write that is asserted while `o_full` is high is
   ignored and `wr_addr` does not advance.
2. **Read pointer:** `rd_addr` advances on `i_rd & !o_empty`. A read asserted
   while `o_empty` is high is ignored and `rd_addr` does not advance.
3. **Read data (combinational):** `o_data = mem[rd_addr]`. The output word
   tracks the current read-pointer location with no register delay.
4. **Empty flag:** `o_empty = (wr_addr == rd_addr)`.
5. **Full flag:** `o_full = ((wr_addr + 1) == rd_addr)`.
6. **Reset:** Async active-low reset clears memory and both pointers to 0. On
   `negedge i_rstn`, `mem`, `wr_addr`, and `rd_addr` are all 0; therefore after
   reset `o_empty` is high and `o_data = mem[0]`.

The full condition reserves one slot (`(wr_addr + 1) == rd_addr`), so the usable
occupancy is 7 of the 8 physical entries — this is part of the contract and is
reproduced exactly.

## 4. Corner Cases

- **Modulo-8 pointer wrap:** Both pointers are 3-bit and wrap modulo-8. The
  full/empty flags use 3-bit pointer wrap (modulo-8); the
  `(wr_addr+1)==rd_addr` full condition is part of the contract and must be
  reproduced exactly (one entry reserved).
- **Write while full:** A write asserted while `o_full` is high is ignored;
  `wr_addr` does not advance and `mem` is not updated.
- **Read while empty:** A read asserted while `o_empty` is high is ignored;
  `rd_addr` does not advance. Because the read is combinational, `o_data`
  continues to present `mem[rd_addr]` (stale/whatever currently resides there) —
  consumers must gate on `o_empty`.
- **Simultaneous write+read:** With independent write/read enables and a shared
  clock, a same-cycle write and read each advance their own pointer under their
  own gate; there is no special bypass — `o_data` reflects `mem[rd_addr]` as of
  the current pointer.
- **Result-FIFO empty read (SC-003):** Reading beyond available result words via
  the APB read path exercises result-FIFO empty/wrap behavior; `o_empty` stays
  high and `rd_addr` is held.

## 5. Verification Hints

The check hints live in `check-hints/fifo.json`.
