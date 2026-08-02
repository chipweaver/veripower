// Testbench top for {{TOP}}.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
module {{TOP}}_tb_top;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  import {{MODULE}}_tb_pkg::*;

  // --- Clock & reset generation ---
  // rst_n is the bench's reset, active-low whatever the DUT's polarity is, so every agent
  // reads it the same way. The DUT port below is driven through the polarity the spec
  // declared for it.
  logic clk;
  logic rst_n;
{{EXTRA_CLOCK_DECLS}}
  initial begin
    clk = 0;
    forever #{{CLK_HALF_PERIOD}} clk = ~clk;
  end
{{EXTRA_CLOCK_GENS}}
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
    .{{RST_PORT_NAME}}({{RST_DRIVE}}){{EXTRA_CLOCK_PORTS}}{{DUT_PORT_MAP}}
  );

  // --- UVM config_db & test launch ---
  initial begin
{{CONFIG_DB_SETS}}
    run_test();
  end
endmodule
