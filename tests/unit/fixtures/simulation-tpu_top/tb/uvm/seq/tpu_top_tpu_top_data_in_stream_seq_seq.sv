// Sequence: tpu_top_data_in_stream_seq (agent: data_in).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: Drive input pairs on in1/in2 with in1_en/in2_en asserted to push words into the two input FIFOs.
class tpu_top_tpu_top_data_in_stream_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_data_in_stream_seq_seq)

  function new(string name = "tpu_top_tpu_top_data_in_stream_seq_seq");
    super.new(name);
  endfunction

  // Push input pairs into the two input FIFOs with in1_en/in2_en asserted.
  // SC-001 streams 4 pairs: in1 = 1,3,5,7 / in2 = 2,4,6,8 (within the 7-usable
  // FIFO depth). Ends with an idle txn so the enables drop before the pass.
  task body();
    tpu_top_data_in_txn txn;
    logic [31:0] a1 [4]; logic [31:0] a2 [4];
    // Wide input operands to toggle the full 32-bit in1/in2/skew/MAC/o_prdata
    // datapath (Rule B stimulus iterate for the toggle dim). RM is data-driven
    // and the 32-bit MAC multiply/accumulate wraps modulo 2^32 (compared with
    // === each cycle), so these wider words stay self-consistent and also
    // exercise the overflow-wrap intent.
    a1[0]=32'hDEAD_BEEF; a1[1]=32'h1234_5678; a1[2]=32'hFFFF_FFFF; a1[3]=32'h8000_0001;
    a2[0]=32'hCAFE_BABE; a2[1]=32'h8765_4321; a2[2]=32'hAAAA_5555; a2[3]=32'h7FFF_FFFE;
    for (int i = 0; i < 4; i++) begin
      txn = tpu_top_data_in_txn::type_id::create("txn");
      start_item(txn);
      txn.in1    = a1[i];
      txn.in2    = a2[i];
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
