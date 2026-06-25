// Sequence: tpu_top_rerun_seq (agent: core).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: Re-assert start with no new weights/inputs so done rises again on existing pipeline/FIFO contents (SC-003).
class tpu_top_tpu_top_rerun_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_rerun_seq_seq)

  function new(string name = "tpu_top_tpu_top_rerun_seq_seq");
    super.new(name);
  endfunction

  // SC-003 re-run: re-assert start with no new weights/inputs so the counter
  // again advances 0→5 and done rises on the existing pipeline/FIFO contents.
  // Hold start high 8 cycles, then deassert (counter resets, done drops). APB
  // strobes held low throughout.
  task body();
    tpu_top_core_txn txn;
    for (int c = 0; c < 8; c++) begin
      txn = tpu_top_core_txn::type_id::create("txn");
      start_item(txn);
      txn.i_psel = 1'b0; txn.i_penable = 1'b0; txn.i_pwrite = 1'b0;
      txn.start  = 1'b1;
      finish_item(txn);
    end
    txn = tpu_top_core_txn::type_id::create("idle");
    start_item(txn);
    txn.i_psel = 1'b0; txn.i_penable = 1'b0; txn.i_pwrite = 1'b0;
    txn.start  = 1'b0;
    finish_item(txn);
  endtask
endclass
