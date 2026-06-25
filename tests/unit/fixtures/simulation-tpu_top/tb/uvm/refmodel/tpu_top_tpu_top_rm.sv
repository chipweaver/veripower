// Cycle-accurate reference model: tpu_top_rm (rev 0.3 — multi-observable).
//
// Full behavioral mirror of the tpu_top datapath, advanced exactly one clock per
// cycle once BOTH input streams (data_in / core) have delivered that cycle's
// sample (keyed by the absolute cycle stamp `cyc`, so arrival order across the
// two ports is irrelevant). The `core` txn carries the apb access inputs AND the
// ctrl `start` input (one active agent merges apb/ctrl/status).
//
// Each step reproduces the DUT's posedge evaluation:
//   1. compute every COMBINATIONAL signal from the CURRENT register state +
//      current inputs (FIFO flags o_full/o_empty, FIFO o_data, fifo_en,
//      result_fifo_wr, the counter-routed result mux, write_enb/read_enb,
//      o_prdata, done) — and RECORD the per-cycle prediction of all five
//      compared observables here, from the SAME current state the monitor
//      samples pre-edge (o_prdata, done, counter, o_full, o_empty);
//   2. compute and commit every REGISTERED next-state value from those
//      combinational values (FIFOs, systolic skew regs, the 4 MAC cells, the
//      counter FSM, the weight mem).
// This ordering is what makes the prediction cycle-accurate. done/counter/
// o_full/o_empty are independently predicted per cycle (NOT mirrored from the
// DUT) and exposed for comparison alongside o_prdata.
//
// The scoreboard polls these predictions per cycle in check_phase and compares
// each against the DUT-observed value with 4-state (`===`) equality. The weight
// mem is modelled as 0 until written (the DUT regfile has NO reset — spec
// faithful); the rev-0.3 tests always load weights via APB before reading
// results, so the unwritten-weight=0 model never produces a spurious X compare.
`uvm_analysis_imp_decl(_data_in)
`uvm_analysis_imp_decl(_core)
class tpu_top_tpu_top_rm extends uvm_component;
  `uvm_component_utils(tpu_top_tpu_top_rm)

  uvm_analysis_imp_data_in #(tpu_top_data_in_txn, tpu_top_tpu_top_rm) ai_data_in;
  uvm_analysis_imp_core #(tpu_top_core_txn, tpu_top_tpu_top_rm) ai_core;

  // ----- per-cycle input buffers (keyed by absolute cycle stamp) -----
  tpu_top_data_in_txn q_data_in[longint unsigned];
  tpu_top_core_txn    q_core[longint unsigned];
  longint unsigned    next_cyc;            // next cycle to process

  // ----- DUT state mirrors -----
  // Weight register file mem[0..3] (clocked write, NOT reset — ref-faithful).
  logic [31:0] mem [0:3];

  // Input FIFOs (fifo_00, fifo_01) and result FIFO (fifo_result): 8x32, 3-bit
  // modulo-8 pointers, combinational read, write reserves one slot.
  logic [31:0] f00_mem [0:7]; logic [2:0] f00_wr, f00_rd;
  logic [31:0] f01_mem [0:7]; logic [2:0] f01_wr, f01_rd;
  logic [31:0] fr_mem  [0:7]; logic [2:0] fr_wr,  fr_rd;

  // systolic_reg skew lines.
  logic [31:0] delay10, delay20, delay21;

  // MAC cell registered outputs: o_result / o_data_next for the four cells.
  logic [31:0] mac00_res, mac01_res, mac10_res, mac11_res;
  logic [31:0] mac00_dn,  mac01_dn,  mac10_dn,  mac11_dn;

  // Counter FSM.
  logic [3:0]  counter_r;

  // ----- per-cycle predictions consumed by the scoreboard -----
  // Recorded for EVERY processed cycle (not just reads), so the scoreboard can
  // compare all five observables each cycle. Keyed by absolute cycle stamp.
  logic [31:0] exp_prdata [longint unsigned]; // APB read-back word (comb)
  logic [3:0]  exp_counter[longint unsigned]; // current (pre-edge) counter value
  logic [2:0]  exp_full   [longint unsigned]; // {fr,f01,f00} full flags (comb)
  logic [2:0]  exp_empty  [longint unsigned]; // {fr,f01,f00} empty flags (comb)
  logic        exp_done   [longint unsigned]; // (counter >= 5) (comb)

  function new(string name = "tpu_top_tpu_top_rm", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    ai_data_in = new("ai_data_in", this);
    ai_core = new("ai_core", this);
    reset();
  endfunction

  // ---- input handlers: buffer by cycle stamp, then drain ----
  virtual function void write_data_in(tpu_top_data_in_txn txn);
    q_data_in[txn.cyc] = txn;
    drain();
  endfunction

  virtual function void write_core(tpu_top_core_txn txn);
    q_core[txn.cyc] = txn;
    drain();
  endfunction

  // Process all cycles for which both input streams have arrived, in order.
  virtual function void drain();
    while (q_data_in.exists(next_cyc) && q_core.exists(next_cyc)) begin
      step(q_data_in[next_cyc], q_core[next_cyc]);
      q_data_in.delete(next_cyc);
      q_core.delete(next_cyc);
      next_cyc = next_cyc + 1;
    end
  endfunction

  // Advance the model one clock. `din`/`core` are this cycle's sampled inputs;
  // the model reproduces the DUT's combinational-then-registered eval and
  // records the five compared observables from the CURRENT (pre-edge) state.
  virtual function void step(tpu_top_data_in_txn din,
                             tpu_top_core_txn core);
    // ---- combinational layer (from CURRENT register state + current inputs) ----
    bit          f00_empty, f00_full, f01_empty, f01_full, fr_empty, fr_full;
    logic [31:0] f00_odata, f01_odata, fr_odata;
    bit          write_enb, read_enb;
    bit          fifo_en, result_fifo_wr;
    logic [31:0] systolic_in1, systolic_in2;
    logic [31:0] out1, out2;          // bottom-row mac results (registered now)
    logic [31:0] result_fifo_i_data;
    logic [2:0]  full_bus, empty_bus;
    logic [31:0] prdata;
    logic        done_now;

    // ---- next-state temporaries (so the registered layer commits as one edge) ----
    logic [31:0] n_delay10, n_delay20, n_delay21;
    logic [31:0] n_mac00_res, n_mac01_res, n_mac10_res, n_mac11_res;
    logic [31:0] n_mac00_dn,  n_mac01_dn,  n_mac10_dn,  n_mac11_dn;
    logic [3:0]  n_counter;

    // FIFO flags (combinational, 3-bit modulo-8 pointer compare). These match
    // the DUT exactly: o_empty=(wr==rd), o_full=((wr+1)==rd).  [CHK-FIFO-04/05]
    f00_empty = (f00_wr == f00_rd);  f00_full = ((f00_wr + 3'd1) == f00_rd);
    f01_empty = (f01_wr == f01_rd);  f01_full = ((f01_wr + 3'd1) == f01_rd);
    fr_empty  = (fr_wr  == fr_rd);   fr_full  = ((fr_wr  + 3'd1) == fr_rd);

    // Top-level status buses: {fifo_result, fifo_01, fifo_00} = [2],[1],[0].
    full_bus  = {fr_full,  f01_full,  f00_full};
    empty_bus = {fr_empty, f01_empty, f00_empty};

    // FIFO combinational read: o_data = mem[rd_addr].  [CHK-FIFO-03]
    f00_odata = f00_mem[f00_rd];
    f01_odata = f01_mem[f01_rd];
    fr_odata  = fr_mem[fr_rd];

    // systolic_reg inputs come combinationally from the input FIFO read ports.
    systolic_in1 = f00_odata;
    systolic_in2 = f01_odata;

    // APB-decoded strobes (combinational).  [CHK-TOP-01/02]
    write_enb = core.i_psel & core.i_penable &  core.i_pwrite;
    read_enb  = core.i_psel & core.i_penable & ~core.i_pwrite;

    // F-05 control terms (combinational, from current counter).  [CHK-TOP-05/06]
    fifo_en        = core.start & (counter_r < 4'd2);
    result_fifo_wr = (counter_r >= 4'd2) & (counter_r <= 4'd5);

    // done = (counter >= 5), combinational.  [CHK-TOP-08]
    done_now = (counter_r >= 4'd5);

    // Counter-routed result mux (combinational): out1 at {2,4}, out2 at {3,5}.
    // out1/out2 here are the CURRENT (registered) bottom-row MAC results.  [CHK-TOP-07/09]
    out1 = mac10_res;
    out2 = mac11_res;
    case (counter_r)
      4'd2, 4'd4: result_fifo_i_data = out1;
      4'd3, 4'd5: result_fifo_i_data = out2;
      default:    result_fifo_i_data = 32'h0;
    endcase

    // APB read output (combinational): result-FIFO o_data on read, else 0.  [CHK-TOP-02]
    if (read_enb)
      prdata = fr_odata;
    else
      prdata = 32'h0;

    // ---- record the FIVE compared observables for this cycle, from the SAME
    // current (pre-edge) state the core monitor sampled with input #1step ----
    exp_prdata [core.cyc] = prdata;
    exp_counter[core.cyc] = counter_r;     // current registered counter value
    exp_full   [core.cyc] = full_bus;
    exp_empty  [core.cyc] = empty_bus;
    exp_done   [core.cyc] = done_now;

    // ---- registered layer: compute every next-state value from CURRENT state
    // (a SV function forbids non-blocking assigns, so next-state is staged in
    // temporaries from current register values, then committed at the end —
    // reproducing the DUT's simultaneous posedge update of all registers). ----

    // Weight register file: clocked write on write_enb, no reset. (Independent
    // of the other registers; safe to commit in place.)
    if (write_enb)
      mem[core.i_paddr[1:0]] = core.i_pwdata;

    // Input FIFO fifo_00: write on in1_en & !full; read advances on fifo_en & !empty.
    if (din.in1_en && !f00_full) begin
      f00_mem[f00_wr] = din.in1;
      f00_wr = f00_wr + 3'd1;
    end
    if (fifo_en && !f00_empty)
      f00_rd = f00_rd + 3'd1;

    // Input FIFO fifo_01.
    if (din.in2_en && !f01_full) begin
      f01_mem[f01_wr] = din.in2;
      f01_wr = f01_wr + 3'd1;
    end
    if (fifo_en && !f01_empty)
      f01_rd = f01_rd + 3'd1;

    // Result FIFO fifo_result: write on result_fifo_wr & !full; read on read_enb & !empty.
    if (result_fifo_wr && !fr_full) begin
      fr_mem[fr_wr] = result_fifo_i_data;
      fr_wr = fr_wr + 3'd1;
    end
    if (read_enb && !fr_empty)
      fr_rd = fr_rd + 3'd1;

    // systolic_reg skew lines: out1=in1 delayed 1, out2=in2 delayed 2.
    n_delay10 = systolic_in1;
    n_delay20 = systolic_in2;
    n_delay21 = delay20;           // uses CURRENT delay20

    // MAC array. Top row: i_pre_result tied 0. Bottom row chains the top-row
    // column partial sums. i_data feeds: top-row from systolic outputs
    // (delay10->mac00, delay21->mac10); right column from the left cell's
    // registered data-forward (mac00_dn->mac01, mac10_dn->mac11). Every RHS
    // uses CURRENT register state, matching the DUT's simultaneous update.
    n_mac00_res = (delay10  * mem[0]) + 32'h0;
    n_mac01_res = (mac00_dn * mem[1]) + 32'h0;
    n_mac10_res = (delay21  * mem[2]) + mac00_res;   // + current top-row col sum
    n_mac11_res = (mac10_dn * mem[3]) + mac01_res;

    n_mac00_dn = delay10;
    n_mac01_dn = mac00_dn;
    n_mac10_dn = delay21;
    n_mac11_dn = mac10_dn;

    // Counter FSM: increment while start, else reset to 0.  [CHK-TOP-04/10]
    n_counter = core.start ? (counter_r + 4'd1) : 4'd0;

    // ---- commit all staged next-state values simultaneously ----
    delay10 = n_delay10; delay20 = n_delay20; delay21 = n_delay21;
    mac00_res = n_mac00_res; mac01_res = n_mac01_res;
    mac10_res = n_mac10_res; mac11_res = n_mac11_res;
    mac00_dn = n_mac00_dn; mac01_dn = n_mac01_dn;
    mac10_dn = n_mac10_dn; mac11_dn = n_mac11_dn;
    counter_r = n_counter;
  endfunction

  // Reset all state mirrors to power-on / async-reset values.
  // (The weight mem is NOT reset in the DUT; initialized to 0 here only for
  // deterministic prediction — every test loads weights via APB before reading.)
  virtual function void reset();
    int i;
    next_cyc = 0;
    q_data_in.delete();
    q_core.delete();
    exp_prdata.delete();
    exp_counter.delete();
    exp_full.delete();
    exp_empty.delete();
    exp_done.delete();
    for (i = 0; i < 4; i++) mem[i] = 32'h0;
    for (i = 0; i < 8; i++) begin
      f00_mem[i] = 32'h0; f01_mem[i] = 32'h0; fr_mem[i] = 32'h0;
    end
    f00_wr = 0; f00_rd = 0;
    f01_wr = 0; f01_rd = 0;
    fr_wr  = 0; fr_rd  = 0;
    delay10 = 0; delay20 = 0; delay21 = 0;
    mac00_res = 0; mac01_res = 0; mac10_res = 0; mac11_res = 0;
    mac00_dn  = 0; mac01_dn  = 0; mac10_dn  = 0; mac11_dn  = 0;
    counter_r = 0;
  endfunction

  // Scoreboard query: returns 1 and the five predicted observables for `cyc` if
  // the model processed that cycle (every processed cycle records a prediction).
  virtual function bit get_expected(longint unsigned cyc,
                                    output logic [31:0] e_prdata,
                                    output logic [3:0]  e_counter,
                                    output logic [2:0]  e_full,
                                    output logic [2:0]  e_empty,
                                    output logic        e_done);
    if (exp_counter.exists(cyc)) begin
      e_prdata  = exp_prdata[cyc];
      e_counter = exp_counter[cyc];
      e_full    = exp_full[cyc];
      e_empty   = exp_empty[cyc];
      e_done    = exp_done[cyc];
      return 1;
    end
    return 0;
  endfunction
endclass
