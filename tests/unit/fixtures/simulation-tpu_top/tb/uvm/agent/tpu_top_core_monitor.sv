// Monitor for core agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class tpu_top_core_monitor extends uvm_monitor;
  `uvm_component_utils(tpu_top_core_monitor)

  uvm_analysis_port #(tpu_top_core_txn) ap;
  virtual tpu_top_core_if vif;

  function new(string name = "tpu_top_core_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    ap = new("ap", this);
    if (!uvm_config_db#(virtual tpu_top_core_if)::get(this, "", "vif", vif))
      `uvm_fatal(get_type_name(), "Virtual interface not found in config_db")
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      tpu_top_core_txn txn;
      txn = tpu_top_core_txn::type_id::create("txn");
      sample_txn(txn);
      ap.write(txn);
    end
  endtask

  // Sample the core group every clock (one txn/cycle): the driven apb access +
  // ctrl inputs AND EVERY DUT output the scoreboard must check —
  //   o_prdata (combinational APB read-back), counter (registered ctrl count),
  //   o_full / o_empty (combinational FIFO flags), done (combinational counter>=5)
  // — stamped with the absolute cycle index. mon_cb (input #1step) captures the
  // stable pre-edge values: the combinational outputs settle from this cycle's
  // inputs + current state, and `counter` is its value heading into this edge.
  // This single observer txn carries all five observables so the scoreboard can
  // compare each against the RM prediction (rev 0.2+: not just o_prdata).
  virtual task sample_txn(tpu_top_core_txn txn);
    @(vif.mon_cb);
    txn.i_paddr   = vif.mon_cb.i_paddr;
    txn.i_psel    = vif.mon_cb.i_psel;
    txn.i_pwrite  = vif.mon_cb.i_pwrite;
    txn.i_pwdata  = vif.mon_cb.i_pwdata;
    txn.i_penable = vif.mon_cb.i_penable;
    txn.start     = vif.mon_cb.start;
    txn.o_prdata  = vif.mon_cb.o_prdata;
    txn.counter   = vif.mon_cb.counter;
    txn.o_full    = vif.mon_cb.o_full;
    txn.o_empty   = vif.mon_cb.o_empty;
    txn.done      = vif.mon_cb.done;
    txn.cyc       = vif.cyc;
  endtask
endclass
