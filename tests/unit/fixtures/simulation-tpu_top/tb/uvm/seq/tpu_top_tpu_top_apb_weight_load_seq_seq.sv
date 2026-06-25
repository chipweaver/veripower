// Sequence: tpu_top_apb_weight_load_seq (agent: core).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: Program the four weights W00..W11 via APB writes to mem[0..3] (i_psel & i_penable & i_pwrite).
class tpu_top_tpu_top_apb_weight_load_seq_seq extends tpu_top_base_seq;
  `uvm_object_utils(tpu_top_tpu_top_apb_weight_load_seq_seq)

  function new(string name = "tpu_top_tpu_top_apb_weight_load_seq_seq");
    super.new(name);
  endfunction

  // Program the four weights W00..W11 via APB writes to mem[0..3]
  // (write_enb = i_psel & i_penable & i_pwrite). SC-001 weight matrix
  // W = [[1,2],[3,4]] → mem[0..3] = 1,2,3,4. start held low. Ends with an idle
  // txn so the held APB strobes are deasserted before the next sequence.
  task body();
    tpu_top_core_txn txn;
    logic [31:0] w [4];
    // Wide weights to toggle the full 32-bit i_pwdata/mem/MAC datapath (Rule B
    // stimulus iterate for the toggle dim). Mix of high-bit / alternating
    // patterns; RM is data-driven (recomputes from driven values) so it stays
    // self-consistent across the wider operands.
    w[0] = 32'hA5A5_5A5A; w[1] = 32'h0F0F_F0F0; w[2] = 32'hFFFF_0001; w[3] = 32'h8001_7FFE;  // W00,W01,W10,W11
    for (int a = 0; a < 4; a++) begin
      txn = tpu_top_core_txn::type_id::create("txn");
      start_item(txn);
      txn.i_paddr   = a;
      txn.i_pwdata  = w[a];
      txn.i_psel    = 1'b1;
      txn.i_penable = 1'b1;
      txn.i_pwrite  = 1'b1;   // write access
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
