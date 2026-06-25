// Sequence: tpu_top_apb_result_read_seq (agent: core).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: APB reads (i_psel & i_penable & !i_pwrite) to pop result words from fifo_result via o_prdata.
class tpu_top_tpu_top_apb_result_read_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_apb_result_read_seq_seq)

  function new(string name = "tpu_top_tpu_top_apb_result_read_seq_seq");
    super.new(name);
  endfunction

  // Pop the four result words from fifo_result via APB reads
  // (read_enb = i_psel & i_penable & !i_pwrite → o_prdata = fifo_result.o_data,
  // rd pointer advances). Each read is a one-cycle access; start held low. Ends
  // with an idle.
  task body();
    tpu_top_core_txn txn;
    for (int i = 0; i < 4; i++) begin
      txn = tpu_top_core_txn::type_id::create("txn");
      start_item(txn);
      txn.i_paddr   = '0;
      txn.i_pwdata  = '0;
      txn.i_psel    = 1'b1;
      txn.i_penable = 1'b1;
      txn.i_pwrite  = 1'b0;   // read access
      txn.start     = 1'b0;
      finish_item(txn);
    end
    // Trailing idle.
    txn = tpu_top_core_txn::type_id::create("idle");
    start_item(txn);
    txn.i_psel = 1'b0; txn.i_penable = 1'b0; txn.i_pwrite = 1'b0; txn.start = 1'b0;
    finish_item(txn);
  endtask
endclass
