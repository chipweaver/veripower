// Testbench top for {{TOP}}.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
module {{TOP}}_tb_top;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  import {{MODULE}}_tb_pkg::*;

  // --- Clock & reset generation ---
  logic clk;
  logic rst_n;

  initial begin
    clk = 0;
    forever #{{CLK_HALF_PERIOD}} clk = ~clk;
  end

  initial begin
    rst_n = 0;
    #20 rst_n = 1;
  end

  // --- Interface instantiation ---
{{IF_INSTANTIATIONS}}

  // --- DUT instantiation (auto-rendered) ---
  // Add hand-written port connections for any DUT ports not covered by agents.
  {{TOP}} u_dut(
    .{{CLK_PORT_NAME}}(clk),
    .{{RST_PORT_NAME}}(rst_n){{DUT_PORT_MAP}}
  );

  // --- UVM config_db & test launch ---
  initial begin
{{CONFIG_DB_SETS}}
    run_test();
  end
endmodule
