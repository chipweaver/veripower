// Testbench top for tpu_top.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
module tpu_top_tb_top;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  import tpu_top_tb_pkg::*;

  // --- Clock & reset generation ---
  logic clk;
  logic rst_n;

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  initial begin
    rst_n = 0;
    #20 rst_n = 1;
  end

  // --- Interface instantiation ---
  tpu_top_data_in_if data_in_if(.clk(clk), .rst_n(rst_n));
  tpu_top_core_if core_if(.clk(clk), .rst_n(rst_n));

  // --- DUT instantiation (auto-rendered) ---
  // Add hand-written port connections for any DUT ports not covered by agents.
  tpu_top u_dut(
    .i_clk(clk),
    .i_rstn(rst_n),
    .in1(data_in_if.in1),
    .in2(data_in_if.in2),
    .in1_en(data_in_if.in1_en),
    .in2_en(data_in_if.in2_en),
    .i_paddr(core_if.i_paddr),
    .i_psel(core_if.i_psel),
    .i_pwrite(core_if.i_pwrite),
    .i_pwdata(core_if.i_pwdata),
    .i_penable(core_if.i_penable),
    .o_prdata(core_if.o_prdata),
    .start(core_if.start),
    .counter(core_if.counter),
    .o_full(core_if.o_full),
    .o_empty(core_if.o_empty),
    .done(core_if.done)
  );

  // --- UVM config_db & test launch ---
  initial begin
    // Each agent's driver/monitor does get(this, "", "vif", ...), so the vif is
    // published under the field key "vif" scoped to that agent's subtree.
    uvm_config_db#(virtual tpu_top_data_in_if)::set(null, "uvm_test_top.m_env.m_data_in_agent*", "vif", data_in_if);
    uvm_config_db#(virtual tpu_top_core_if)::set(null, "uvm_test_top.m_env.m_core_agent*", "vif", core_if);
    run_test();
  end
endmodule
