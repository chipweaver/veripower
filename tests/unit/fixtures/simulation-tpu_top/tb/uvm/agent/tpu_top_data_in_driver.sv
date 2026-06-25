// Driver for data_in agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class tpu_top_data_in_driver extends uvm_driver #(tpu_top_data_in_txn);
  `uvm_component_utils(tpu_top_data_in_driver)

  virtual tpu_top_data_in_if vif;

  function new(string name = "tpu_top_data_in_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual tpu_top_data_in_if)::get(this, "", "vif", vif))
      `uvm_fatal(get_type_name(), "Virtual interface not found in config_db")
  endfunction

  task run_phase(uvm_phase phase);
    tpu_top_data_in_txn txn;
    // Idle the input bus until reset deasserts.
    vif.in1    = '0;
    vif.in2    = '0;
    vif.in1_en = 1'b0;
    vif.in2_en = 1'b0;
    @(posedge vif.rst_n);
    // Blocking get_next_item drives gaplessly within a sequence. Each sequence
    // ends with an explicit idle txn (enables low) so the value held between
    // sequences is benign (no spurious FIFO writes).
    forever begin
      seq_item_port.get_next_item(txn);
      drive_txn(txn);
      seq_item_port.item_done();
    end
  endtask

  // One txn == one clock of data_in stimulus. Wait for the clocking edge first,
  // then assign — each txn lands on its own cycle (assigning before the wait
  // races the first edge and drops the first txn).
  virtual task drive_txn(tpu_top_data_in_txn txn);
    @(vif.drv_cb);
    vif.drv_cb.in1    <= txn.in1;
    vif.drv_cb.in2    <= txn.in2;
    vif.drv_cb.in1_en <= txn.in1_en;
    vif.drv_cb.in2_en <= txn.in2_en;
  endtask
endclass
