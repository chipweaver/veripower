---
child: mac
parent: tpu_top
brainstorm_anchor: "lines 44-57"
ports:
  - i_clk
  - i_rstn
  - mac00_in
  - mac00_out
  - mac01_in
  - mac01_out
  - mac10_in
  - mac11_in
  - "mem[0]"
  - "mem[1]"
  - "mem[2]"
  - "mem[3]"
  - "32'h0"
  - out1
  - out2
clocks:
  - { name: i_clk, domain: i_clk }
features:
  - F-01
---

# §1 Purpose

`mac` is the single multiply-accumulate (MAC) cell that implements feature **F-01**
(2×2 weight-stationary MAC array). It is a leaf compute element instantiated **4×**
in `tpu_top` as `mac_00`, `mac_01`, `mac_10`, `mac_11`, arranged as a 2×2
weight-stationary systolic array.

Each cell holds one stationary weight (`i_weight`), multiplies it by the incoming
data word (`i_data`), and adds the partial sum arriving from the cell above
(`i_pre_result`), producing a registered result (`o_result`). In parallel it
forwards its input data one cell to the right (`o_data_next <= i_data`), so a data
word ripples along its row one cycle per cell.

Weight-stationary means the weight stays loaded in the cell (driven from the parent
register file `mem[0..3]`) while data and partial sums flow through. The vertical
partial-sum chain accumulates a column's products: `mac_00 → mac_10` (column 0) and
`mac_01 → mac_11` (column 1). The top-row cells `mac_00`/`mac_01` are seeded with a
constant `32'h0` partial sum, so they act as pure multiply stages; the bottom-row
cells `mac_10`/`mac_11` add their column's top-row product to form the final result
words `out1`/`out2`.

Implementation strategy: a minimal registered datapath — one synchronous result
register and one synchronous data-forward register, both cleared by the
asynchronous active-low reset. No saturation, no overflow protection, no
configurability: arithmetic is fixed 32-bit and wraps. This reproduces the
known-good reference cell behavior exactly so the cycle-level schedule matches the
existing directed testbench.

# §2 Interface

The `mac` module has five logical ports — `i_data`, `i_weight`, `i_pre_result`,
`o_result`, `o_data_next` — plus the shared clock/reset. The table below maps each
`tpu_top` inter-module net (frontmatter `ports`) to the actual `mac` instance port
it connects to. All ports are in the single `i_clk` domain.

| tpu_top Net | mac Instance.Port | Direction (at mac) | Width | Clock Domain | Protocol | Timing |
|-------------|-------------------|--------------------|-------|--------------|----------|--------|
| `i_clk` | all four cells `.i_clk` | input | 1 | i_clk | clock | rising-edge (`posedge i_clk`) |
| `i_rstn` | all four cells `.i_rstn` | input | 1 | i_clk (async assert) | reset | async active-low (`negedge i_rstn`) → registers to 0 |
| `mac00_in` | `mac_00.i_data` | input | 32 | i_clk | registered datapath | sampled at `posedge i_clk` (from `systolic_reg.out1`, in1 skew 1 cyc) |
| `mac10_in` | `mac_10.i_data` | input | 32 | i_clk | registered datapath | sampled at `posedge i_clk` (from `systolic_reg.out2`, in2 skew 2 cyc) |
| `mac01_in` | `mac_01.i_data` | input | 32 | i_clk | registered datapath | from `mac_00.o_data_next`; data forward (row 0) |
| `mac11_in` | `mac_11.i_data` | input | 32 | i_clk | registered datapath | from `mac_10.o_data_next`; data forward (row 1) |
| `mem[0]` | `mac_00.i_weight` | input | 32 | i_clk | registered (stationary) | weight `W00`; held stable from parent register file |
| `mem[1]` | `mac_01.i_weight` | input | 32 | i_clk | registered (stationary) | weight `W01`; held stable from parent register file |
| `mem[2]` | `mac_10.i_weight` | input | 32 | i_clk | registered (stationary) | weight `W10`; held stable from parent register file |
| `mem[3]` | `mac_11.i_weight` | input | 32 | i_clk | registered (stationary) | weight `W11`; held stable from parent register file |
| `32'h0` | `mac_00.i_pre_result`, `mac_01.i_pre_result` | input | 32 | static | const tie | top-row partial-sum seed; constant `32'h0` |
| `mac00_out` | `mac_00.o_result` → `mac_10.i_pre_result` | output→input | 32 | i_clk | registered datapath | partial sum column 0; available 1 cycle after inputs |
| `mac01_out` | `mac_01.o_result` → `mac_11.i_pre_result` | output→input | 32 | i_clk | registered datapath | partial sum column 1; available 1 cycle after inputs |
| `out1` | `mac_10.o_result` | output | 32 | i_clk | registered datapath | result word A → parent result mux; 1-cycle latency |
| `out2` | `mac_11.o_result` | output | 32 | i_clk | registered datapath | result word B → parent result mux; 1-cycle latency |

Notes:
- `32'h0` is a constant net (not a register); it ties the `i_pre_result` port of the
  two top-row cells to zero so they perform pure multiplies.
- `o_data_next` is a real `mac` output port on all four cells. On `mac_00`/`mac_10`
  it drives `mac01_in`/`mac11_in`. On `mac_01`/`mac_11` it is **intentionally
  unconnected** (see §4), so it is not listed as a `tpu_top` inter-module net.

# §3 Internal Behavior

The cell is purely synchronous with one asynchronous reset. Two registers update
every rising clock edge and are cleared to 0 on the falling edge of `i_rstn`:

| Register | Update (every `posedge i_clk`) | Async reset (`negedge i_rstn`) | Latency |
|----------|--------------------------------|--------------------------------|---------|
| `o_result` | `o_result <= (i_data * i_weight) + i_pre_result` | `o_result <= 0` | 1 cycle from inputs |
| `o_data_next` | `o_data_next <= i_data` | `o_data_next <= 0` | 1 cycle from `i_data` |

Behavioral description (per brainstorm lines 44-47): "Each MAC cell, every clock
(async active-low reset → 0): `o_result <= (i_data * i_weight) + i_pre_result`
(registered); `o_data_next <= i_data` (registered, forwards data to the next cell)."

- **MAC compute:** the product `i_data * i_weight` is a 32-bit multiply truncated to
  32 bits; the partial sum `i_pre_result` is added; the 32-bit accumulate **wraps**
  (no saturation). The result lands in `o_result` one cycle after the inputs are
  presented (happy path: valid `i_data`/`i_weight` → `o_result` reflects the MAC one
  cycle later).
- **Data forward:** `o_data_next` registers `i_data`, forwarding the data word to the
  next cell in the row one cycle later. This realizes the systolic horizontal
  wavefront (`mac_00 → mac_01`, `mac_10 → mac_11`).
- **Partial-sum chain:** vertically, `mac_00.o_result` feeds `mac_10.i_pre_result`
  (column 0) and `mac_01.o_result` feeds `mac_11.i_pre_result` (column 1). The
  top-row cells receive `i_pre_result = 32'h0`.
- **Reset:** asynchronous, active-low (`negedge i_rstn`). On assertion both `o_result`
  and `o_data_next` are driven to 0 immediately, independent of the clock. Single
  reset, no release-ordering constraints.

# §4 Corner Cases

- **32-bit multiply truncation:** `i_data * i_weight` is computed and truncated to 32
  bits; any upper product bits beyond bit 31 are discarded. Accepted by design.
- **32-bit accumulate wrap (no saturation):** `(i_data * i_weight) + i_pre_result`
  is a 32-bit accumulate that **wraps** modulo 2³² on overflow. There is no
  saturation or overflow protection — product/sum exceeding 32 bits wraps and is
  accepted by design (negative case per brainstorm line 57).
- **Top-row `i_pre_result = 0`:** for the top-row cells `mac_00`/`mac_01` the
  `i_pre_result` input is tied to constant `32'h0`, so the cell acts as a pure
  multiply into the partial-sum chain (corner case per brainstorm lines 55-56):
  `o_result <= (i_data * i_weight) + 0`.
- **Intentionally-unconnected outputs:** `mac_01.o_data_next` and
  `mac_11.o_data_next` are intentionally left unconnected at the `tpu_top` level
  (no consumer downstream of the rightmost column). The registers still toggle
  internally; their outputs are simply not routed. This must not be flagged as a
  dangling-driver error.
- **Reset during compute:** an asynchronous `i_rstn` assertion mid-pass clears both
  registers to 0 immediately, discarding any in-flight product/partial sum.

# §5 Verification Hints

| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-MAC-01 | F-01 | Registered MAC: result = data×weight + partial sum, one cycle later | every clock (async active-low reset → 0): `o_result <= (i_data * i_weight) + i_pre_result` (registered) | L46 | `o_result` (`mac00_out`/`mac01_out`/`out1`/`out2`) | `o_result_next = (i_data * i_weight) + i_pre_result`, truncated/wrapped to 32 bits | 1 cycle | `o_result <= 0` on `negedge i_rstn` |
| CHK-MAC-02 | F-01 | Registered data forward to next cell, one cycle later | `o_data_next <= i_data` (registered, forwards data to the next cell) | L47 | `o_data_next` (`mac01_in`/`mac11_in`) | `o_data_next_next = i_data` | 1 cycle | `o_data_next <= 0` on `negedge i_rstn` |
| CHK-MAC-03 | F-01 | 32-bit multiply truncated to 32 bits; 32-bit accumulate wraps (no saturation) | The product `i_data * i_weight` is a 32-bit multiply truncated to 32 bits; the accumulate is 32-bit and **wraps** (no saturation). | L49-L50 | `o_result` MSBs | `o_result = ((i_data * i_weight) + i_pre_result) mod 2^32` | 1 cycle | `o_result <= 0` on `negedge i_rstn` |
| CHK-MAC-04 | F-01 | Top-row cells seeded with zero partial sum → pure multiply | `i_pre_result = 0` (top-row cells `mac_00`/`mac_01`) → cell acts as a pure multiply into the partial-sum chain. | L55-L56 | `mac00_out`/`mac01_out` with `32'h0` tie | for `mac_00`/`mac_01`: `o_result = (i_data * i_weight) + 0` (i_pre_result tied `32'h0`) | 1 cycle | `o_result <= 0` on `negedge i_rstn` |
| CHK-MAC-05 | F-01 | Partial-sum chain: top-row result feeds bottom-row i_pre_result per column | `o_result <= (i_data * i_weight) + i_pre_result` (registered) — column chain `mac00_out`→`mac_10.i_pre_result`, `mac01_out`→`mac_11.i_pre_result` | L46 | `out1` (`mac_10.o_result`), `out2` (`mac_11.o_result`) | `out1 = (mac10.i_data * mem[2]) + mac00_out`; `out2 = (mac11.i_data * mem[3]) + mac01_out` | 1 cycle per cell | `o_result <= 0` on `negedge i_rstn` |
| CHK-MAC-06 | F-01 | Negative: product/sum > 32 bits wraps, accepted | Negative case: product/sum exceeding 32 bits wraps — accepted by design. | L57 | `o_result` on overflow stimulus | result wraps modulo 2^32; no saturation, no error flag | 1 cycle | `o_result <= 0` on `negedge i_rstn` |
| CHK-MAC-07 | F-01 | Intentionally-unconnected o_data_next on right-column cells | `o_data_next <= i_data` (registered) — `mac_01.o_data_next` / `mac_11.o_data_next` intentionally unconnected | L47 (narrative-only; see L160 design §1.4.2) | `mac_01.o_data_next`, `mac_11.o_data_next` (no consumer) | output left dangling by design; not a connectivity error | 1 cycle | `o_data_next <= 0` on `negedge i_rstn` |
