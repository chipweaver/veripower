// Monitor for data_in agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class tpu_top_data_in_monitor extends uvm_monitor;
  `uvm_component_utils(tpu_top_data_in_monitor)

  uvm_analysis_port #(tpu_top_data_in_txn) ap;
  virtual tpu_top_data_in_if vif;

  function new(string name = "tpu_top_data_in_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    ap = new("ap", this);
    if (!uvm_config_db#(virtual tpu_top_data_in_if)::get(this, "", "vif", vif))
      `uvm_fatal(get_type_name(), "Virtual interface not found in config_db")
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      tpu_top_data_in_txn txn;
      txn = tpu_top_data_in_txn::type_id::create("txn");
      sample_txn(txn);
      ap.write(txn);
    end
  endtask

  // Sample the data_in bus every clock (one txn/cycle) and stamp the absolute
  // cycle index from the interface's free-running counter so the RM can order
  // per-port inputs deterministically. Reads use mon_cb (input #1step) to
  // capture the stable pre-edge values the DUT registers this cycle.
  virtual task sample_txn(tpu_top_data_in_txn txn);
    @(vif.mon_cb);
    txn.in1    = vif.mon_cb.in1;
    txn.in2    = vif.mon_cb.in2;
    txn.in1_en = vif.mon_cb.in1_en;
    txn.in2_en = vif.mon_cb.in2_en;
    txn.cyc    = vif.cyc;
  endtask
endclass
