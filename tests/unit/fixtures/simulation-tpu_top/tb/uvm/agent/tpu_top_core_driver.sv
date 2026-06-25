// Driver for core agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class tpu_top_core_driver extends uvm_driver #(tpu_top_core_txn);
  `uvm_component_utils(tpu_top_core_driver)

  virtual tpu_top_core_if vif;

  function new(string name = "tpu_top_core_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual tpu_top_core_if)::get(this, "", "vif", vif))
      `uvm_fatal(get_type_name(), "Virtual interface not found in config_db")
  endfunction

  task run_phase(uvm_phase phase);
    tpu_top_core_txn txn;
    // Idle the apb access + ctrl inputs until reset deasserts.
    vif.i_paddr   = '0;
    vif.i_psel    = 1'b0;
    vif.i_pwrite  = 1'b0;
    vif.i_pwdata  = '0;
    vif.i_penable = 1'b0;
    vif.start     = 1'b0;
    @(posedge vif.rst_n);
    // Blocking get_next_item drives gaplessly within a sequence. Each core
    // sequence ends with an explicit idle txn (apb strobes + start low) so the
    // held value between sequences neither writes mem, pops the result FIFO,
    // nor advances the counter.
    forever begin
      seq_item_port.get_next_item(txn);
      drive_txn(txn);
      seq_item_port.item_done();
    end
  endtask

  // One txn == one clock of core stimulus (APB single-phase access decoded as
  // write_enb/read_enb = i_psel & i_penable & {i_pwrite|~i_pwrite}, plus the
  // counter-gating `start`). Wait for the clocking edge first, then assign — so
  // each txn lands on its own cycle (assigning before the wait races the first
  // edge and drops the first txn). o_* outputs are inputs to this agent and are
  // never driven here.
  virtual task drive_txn(tpu_top_core_txn txn);
    @(vif.drv_cb);
    vif.drv_cb.i_paddr   <= txn.i_paddr;
    vif.drv_cb.i_psel    <= txn.i_psel;
    vif.drv_cb.i_pwrite  <= txn.i_pwrite;
    vif.drv_cb.i_pwdata  <= txn.i_pwdata;
    vif.drv_cb.i_penable <= txn.i_penable;
    vif.drv_cb.start     <= txn.start;
  endtask
endclass
