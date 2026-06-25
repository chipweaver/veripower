// Interface for core agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
interface tpu_top_core_if(input logic clk, input logic rst_n);
  // APB-access + ctrl inputs (driven by the core driver).
  logic [31:0] i_paddr;
  logic        i_psel;
  logic        i_pwrite;
  logic [31:0] i_pwdata;
  logic        i_penable;
  logic        start;
  // DUT outputs (sampled by the core monitor; never driven).
  logic [31:0] o_prdata;
  logic [3:0]  counter;
  logic [2:0]  o_full;
  logic [2:0]  o_empty;
  logic        done;

  // Free-running absolute cycle counter (shared cadence across all interfaces).
  longint unsigned cyc;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) cyc <= '0;
    else        cyc <= cyc + 1;
  end

  // Driver writes the apb/ctrl inputs with output skew; monitor samples all
  // inputs and all outputs with input skew so it captures the stable pre-edge
  // values (o_prdata/o_full/o_empty/done are combinational, counter is the
  // registered value before the upcoming edge).
  clocking drv_cb @(posedge clk);
    default input #1step output #1;
    output i_paddr, i_psel, i_pwrite, i_pwdata, i_penable, start;
    input  o_prdata, counter, o_full, o_empty, done;
  endclocking

  clocking mon_cb @(posedge clk);
    default input #1step;
    input i_paddr, i_psel, i_pwrite, i_pwdata, i_penable, start,
          o_prdata, counter, o_full, o_empty, done;
  endclocking

  modport driver_mp  (clocking drv_cb, input clk, rst_n);
  modport monitor_mp (clocking mon_cb, input clk, rst_n);

endinterface
