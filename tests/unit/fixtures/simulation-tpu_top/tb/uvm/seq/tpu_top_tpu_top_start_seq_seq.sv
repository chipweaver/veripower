// Sequence: tpu_top_start_seq (agent: core).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: Assert start to launch a compute pass; counter advances 1..5; deassert start at end of pass.
class tpu_top_tpu_top_start_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_start_seq_seq)

  function new(string name = "tpu_top_tpu_top_start_seq_seq");
    super.new(name);
  endfunction

  // Assert start to launch one compute pass: counter advances 0→1→2→3→4→5
  // (fifo_en pops at counter<2, results pushed at counter∈{2,3,4,5}, done at
  // counter>=5). Hold start high 8 cycles so the counter reaches and lingers at
  // >=5, then deassert (idle) which resets the counter to 0 and drops done. APB
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
    // Deassert: counter resets to 0, done drops.
    txn = tpu_top_core_txn::type_id::create("idle");
    start_item(txn);
    txn.i_psel = 1'b0; txn.i_penable = 1'b0; txn.i_pwrite = 1'b0;
    txn.start  = 1'b0;
    finish_item(txn);
  endtask
endclass
