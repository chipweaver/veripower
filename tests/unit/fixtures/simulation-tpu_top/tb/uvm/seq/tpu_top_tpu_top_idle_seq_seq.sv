// Sequence: tpu_top_idle_seq (agent: core).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: No traffic: start held low, no APB or data activity (power idle / clock-tree / leakage baseline).
class tpu_top_tpu_top_idle_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_idle_seq_seq)

  function new(string name = "tpu_top_tpu_top_idle_seq_seq");
    super.new(name);
  endfunction

  // Power idle / clock-tree / leakage baseline: no traffic at all. Drive a run
  // of idle cycles with start low and every APB strobe low (no weight write, no
  // result read, counter stays 0, done stays 0). Used only by the power
  // scenarios (S1/S2/S3*/S7); functionally a quiescent hold.
  task body();
    tpu_top_core_txn txn;
    for (int c = 0; c < 8; c++) begin
      txn = tpu_top_core_txn::type_id::create("idle");
      start_item(txn);
      txn.i_paddr   = '0;
      txn.i_pwdata  = '0;
      txn.i_psel    = 1'b0;
      txn.i_penable = 1'b0;
      txn.i_pwrite  = 1'b0;
      txn.start     = 1'b0;
      finish_item(txn);
    end
  endtask
endclass
