// Testbench top for {{TOP}}.
// Generated from scaffold-spec.json and rewritten every round — everything here is derived
// from the plan and the boundary. What this bench drives is authored elsewhere; the one
// hand-written thing it reaches is the reset schedule it includes below.
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
  // --- Interface instantiation ---
{{IF_INSTANTIATIONS}}

  // --- Reset schedule ---
  // Authored, and the only part of this file that is. Included after the interfaces so a
  // reset can be timed against what the bench is driving.
  `include "{{MODULE}}_reset.svh"

  // --- DUT instantiation ---
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
