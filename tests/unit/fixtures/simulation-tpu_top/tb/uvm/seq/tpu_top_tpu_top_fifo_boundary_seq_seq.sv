// Sequence: tpu_top_fifo_boundary_seq (agent: data_in).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: Boundary stimulus on the input FIFOs: write past full / read at empty to exercise ignored writes/reads and modulo-8 pointer wrap.
class tpu_top_tpu_top_fifo_boundary_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_fifo_boundary_seq_seq)

  function new(string name = "tpu_top_tpu_top_fifo_boundary_seq_seq");
    super.new(name);
  endfunction

  // Boundary stimulus on the input FIFOs: write past full to exercise the
  // write-while-full-ignored path and modulo-8 pointer wrap. Push 10 words
  // (> the 7 usable slots) with enables high so later writes hit !o_full=0 and
  // are ignored (pointers do not advance, o_full asserts). Ends with an idle txn.
  task body();
    tpu_top_data_in_txn txn;
    for (int i = 0; i < 10; i++) begin
      txn = tpu_top_data_in_txn::type_id::create("txn");
      start_item(txn);
      txn.in1    = 32'h1000 + i;
      txn.in2    = 32'h2000 + i;
      txn.in1_en = 1'b1;
      txn.in2_en = 1'b1;
      finish_item(txn);
    end
    txn = tpu_top_data_in_txn::type_id::create("idle");
    start_item(txn);
    txn.in1_en = 1'b0; txn.in2_en = 1'b0;
    finish_item(txn);
  endtask
endclass
