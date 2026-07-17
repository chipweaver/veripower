// accum.v — 8-bit synchronous accumulator (generic demo, Verilog-2001).
// Purely a wrapper smoke/example design; unrelated to any evaluated module.
module accum (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    input  wire [7:0] din,
    output reg  [7:0] sum
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)      sum <= 8'd0;
        else if (en)     sum <= sum + din;
    end
endmodule
