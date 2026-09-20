// Interface for {{AGENT_NAME}} agent.
// Generated from the simulation-plan sidecars and specification boundary. Fill domain-labeled stubs per verification-plan.md test strategy.
interface {{MODULE}}_{{AGENT_NAME}}_if(
  `include "{{MODULE}}_reset_ports.svh"
);
  wire clk;  // connected by the authored clock include in tb_top
  `include "{{MODULE}}_{{AGENT_NAME}}_signals.svh"  // generated every round

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
  // Include the relevant reset signals from the generated port list in each modport.
  // modport driver_mp  (clocking drv_cb, input clk);
  // modport monitor_mp (clocking mon_cb, input clk);

endinterface
