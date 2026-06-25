// Interface for data_in agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
interface tpu_top_data_in_if(input logic clk, input logic rst_n);
  logic [31:0] in1;
  logic [31:0] in2;
  logic        in1_en;
  logic        in2_en;

  // Free-running absolute cycle counter (shared cadence across all interfaces:
  // every interface counts the same clk/rst_n identically). The RM uses this to
  // order multi-port per-cycle inputs deterministically.
  longint unsigned cyc;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) cyc <= '0;
    else        cyc <= cyc + 1;
  end

  // Driver writes inputs with output skew; monitor samples with input skew so it
  // captures the stable pre-edge value the DUT registers on this clk.
  clocking drv_cb @(posedge clk);
    default input #1step output #1;
    output in1, in2, in1_en, in2_en;
  endclocking

  clocking mon_cb @(posedge clk);
    default input #1step;
    input in1, in2, in1_en, in2_en;
  endclocking

  modport driver_mp  (clocking drv_cb, input clk, rst_n);
  modport monitor_mp (clocking mon_cb, input clk, rst_n);

endinterface
