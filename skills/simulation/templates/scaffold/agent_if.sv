// Interface for {{AGENT_NAME}} agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
interface {{MODULE}}_{{AGENT_NAME}}_if(input logic clk, input logic rst_n);
{{SIGNAL_DECLARATIONS}}

  // TODO(interface): Add clocking blocks and modports.
  //
  // clocking drv_cb @(posedge clk);
  //   default input #1 output #1;
  //   // output <driven_signals>;
  //   // input  <sampled_signals>;
  // endclocking
  //
  // clocking mon_cb @(posedge clk);
  //   default input #1;
  //   // input <all_observed_signals>;
  // endclocking
  //
  // modport driver_mp  (clocking drv_cb, input clk, rst_n);
  // modport monitor_mp (clocking mon_cb, input clk, rst_n);

endinterface
