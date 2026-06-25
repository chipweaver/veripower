// Scoreboard: tpu_top_scoreboard (rev 0.3 — multi-observable).
//
// compare_txn = tpu_top_core_txn. The single `core` observer txn carries EVERY
// DUT output (plan §2): o_prdata, counter, o_full, o_empty, done. For every
// observed cycle the scoreboard compares EACH of these five against the
// cycle-accurate RM's independently-predicted value with 4-state (`===`)
// equality. Every mismatch is a `uvm_error and increments the real fail_count.
//
// `rm` is the env's single cycle-accurate mirror (wired in by the env in
// connect_phase) — the same RM that received both input streams. The observed
// core txns are buffered by cycle stamp during run; the comparison is drained
// in check_phase, by which point every input has reached the RM and the model
// has processed all completed cycles (arrival-order independent).
class tpu_top_tpu_top_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(tpu_top_tpu_top_scoreboard)

  uvm_analysis_imp #(tpu_top_core_txn, tpu_top_tpu_top_scoreboard) analysis_export;
  tpu_top_tpu_top_rm rm;   // handle to the env's RM (set by env.connect_phase)

  // Observed core transactions, keyed by absolute cycle stamp.
  tpu_top_core_txn obs [longint unsigned];

  int unsigned pass_count;
  int unsigned fail_count;
  int unsigned checked_count;

  function new(string name = "tpu_top_tpu_top_scoreboard", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    analysis_export = new("analysis_export", this);
    pass_count = 0;
    fail_count = 0;
    checked_count = 0;
  endfunction

  virtual function void write(tpu_top_core_txn txn);
    check_txn(txn);
  endfunction

  // Buffer every observed core txn by its cycle stamp. The core monitor emits
  // one txn per cycle carrying all five DUT outputs, so every cycle is a
  // comparison point (not just APB reads).
  virtual function void check_txn(tpu_top_core_txn txn);
    tpu_top_core_txn t = tpu_top_core_txn::type_id::create("obs");
    t.copy(txn);
    obs[txn.cyc] = t;
  endfunction

  // Drain comparisons after all stimulus has been delivered to the RM. For each
  // observed cycle, compare ALL FIVE observables against the RM prediction.
  function void check_phase(uvm_phase phase);
    logic [31:0] e_prdata;
    logic [3:0]  e_counter;
    logic [2:0]  e_full, e_empty;
    logic        e_done;
    super.check_phase(phase);
    if (rm == null)
      `uvm_fatal(get_type_name(), "RM handle not connected to scoreboard")
    foreach (obs[cyc]) begin
      tpu_top_core_txn o = obs[cyc];
      if (!rm.get_expected(cyc, e_prdata, e_counter, e_full, e_empty, e_done)) begin
        // The RM did not produce a prediction for an observed cycle — a real
        // model/observation desync, not a tolerable carve-out.
        fail_count++;
        `uvm_error(get_type_name(),
          $sformatf("No RM prediction for observed cyc=%0d", cyc))
        continue;
      end
      checked_count++;

      // --- o_prdata: APB result read-back (TP-APB-READ / matmul result path) ---
      if (o.o_prdata === e_prdata) begin
        pass_count++;
      end
      else begin
        fail_count++;
        `uvm_error(get_type_name(),
          $sformatf("MISMATCH o_prdata cyc=%0d: DUT=0x%08h expected=0x%08h",
                    cyc, o.o_prdata, e_prdata))
      end

      // --- done: independently predicted as (counter>=5) (TP-CTRL-DONE) ---
      if (o.done === e_done) begin
        pass_count++;
      end
      else begin
        fail_count++;
        `uvm_error(get_type_name(),
          $sformatf("MISMATCH done cyc=%0d: DUT=%0b expected=%0b",
                    cyc, o.done, e_done))
      end

      // --- counter: independently predicted FSM count (TP-CTRL-COUNTER) ---
      if (o.counter === e_counter) begin
        pass_count++;
      end
      else begin
        fail_count++;
        `uvm_error(get_type_name(),
          $sformatf("MISMATCH counter cyc=%0d: DUT=%0d expected=%0d",
                    cyc, o.counter, e_counter))
      end

      // --- o_full: independently predicted FIFO full flags (TP-FIFO-FLAGS) ---
      if (o.o_full === e_full) begin
        pass_count++;
      end
      else begin
        fail_count++;
        `uvm_error(get_type_name(),
          $sformatf("MISMATCH o_full cyc=%0d: DUT=0x%01h expected=0x%01h",
                    cyc, o.o_full, e_full))
      end

      // --- o_empty: independently predicted FIFO empty flags (TP-FIFO-FLAGS) ---
      if (o.o_empty === e_empty) begin
        pass_count++;
      end
      else begin
        fail_count++;
        `uvm_error(get_type_name(),
          $sformatf("MISMATCH o_empty cyc=%0d: DUT=0x%01h expected=0x%01h",
                    cyc, o.o_empty, e_empty))
      end
    end
  endfunction

  function void report_phase(uvm_phase phase);
    `uvm_info(get_type_name(),
      $sformatf("Scoreboard summary: CHECKED=%0d PASS=%0d FAIL=%0d",
                checked_count, pass_count, fail_count), UVM_LOW)
    if (fail_count > 0)
      `uvm_error(get_type_name(),
        $sformatf("Scoreboard detected %0d mismatch(es)", fail_count))
  endfunction
endclass
