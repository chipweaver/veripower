// Sequence: tpu_top_traffic_seq (agent: data_in).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: Sustained business-flow traffic: continuous weight loads + input streams + start passes at the typical rate.
class tpu_top_tpu_top_traffic_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_traffic_seq_seq)

  function new(string name = "tpu_top_tpu_top_traffic_seq_seq");
    super.new(name);
  endfunction

  // business_flow data side (power S4*/S6): sustained input streams looped at
  // the typical rate (the SC-001/SC-002 compute pattern repeated). This is the
  // data_in agent's contribution; the core agent's weight-load/start passes run
  // on the core sequencer for the same scenarios. Pushes 3 passes of 4 pairs.
  task body();
    tpu_top_data_in_txn txn;
    logic [31:0] a1 [4]; logic [31:0] a2 [4];
    a1[0]=32'd1; a1[1]=32'd3; a1[2]=32'd5; a1[3]=32'd7;
    a2[0]=32'd2; a2[1]=32'd4; a2[2]=32'd6; a2[3]=32'd8;
    for (int pass = 0; pass < 3; pass++) begin
      for (int i = 0; i < 4; i++) begin
        txn = tpu_top_data_in_txn::type_id::create("txn");
        start_item(txn);
        txn.in1    = a1[i];
        txn.in2    = a2[i];
        txn.in1_en = 1'b1;
        txn.in2_en = 1'b1;
        finish_item(txn);
      end
      // Gap between passes (enables low) — typical-rate, not back-to-back.
      txn = tpu_top_data_in_txn::type_id::create("gap");
      start_item(txn);
      txn.in1_en = 1'b0; txn.in2_en = 1'b0;
      finish_item(txn);
    end
  endtask
endclass
