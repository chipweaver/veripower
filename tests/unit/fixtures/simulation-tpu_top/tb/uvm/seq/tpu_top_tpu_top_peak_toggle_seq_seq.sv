// Sequence: tpu_top_peak_toggle_seq (agent: data_in).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: Worst-case full-toggle stimulus on all data inputs to maximize switching activity (PDN/IR-drop corner).
class tpu_top_tpu_top_peak_toggle_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_peak_toggle_seq_seq)

  function new(string name = "tpu_top_tpu_top_peak_toggle_seq_seq");
    super.new(name);
  endfunction

  // full_toggle (power S5, PDN/IR-drop corner): maximally-toggling data on all
  // data_in inputs for worst-case switching. Alternate every cycle between
  // all-ones and all-zeros on in1/in2 with enables held high, so every data bit
  // flips each cycle.
  task body();
    tpu_top_data_in_txn txn;
    for (int c = 0; c < 12; c++) begin
      txn = tpu_top_data_in_txn::type_id::create("txn");
      start_item(txn);
      txn.in1    = (c % 2 == 0) ? 32'hFFFFFFFF : 32'h00000000;
      txn.in2    = (c % 2 == 0) ? 32'h00000000 : 32'hFFFFFFFF;
      txn.in1_en = 1'b1;
      txn.in2_en = 1'b1;
      finish_item(txn);
    end
    // Trailing idle (enables low).
    txn = tpu_top_data_in_txn::type_id::create("idle");
    start_item(txn);
    txn.in1_en = 1'b0; txn.in2_en = 1'b0;
    finish_item(txn);
  endtask
endclass
