//-----------------------------------------------------------------------------
// Module      : mac
// Description : Single registered multiply-accumulate (MAC) cell of the 2x2
//               weight-stationary systolic array (feature F-01). Every rising
//               clock edge it computes the MAC of the incoming data word and the
//               stationary weight plus the partial sum from the cell above, and
//               forwards its input data one cell to the right.
//                 o_result    <= (i_data * i_weight) + i_pre_result
//                 o_data_next <= i_data
//               32-bit multiply truncated to 32 bits; 32-bit accumulate wraps
//               modulo 2^32 (no saturation). Asynchronous active-low reset
//               (i_rstn) clears both registers to 0.
// Author      : VeriPower rtl-design
// Created     : 2026-06-17
// Version     : 0.1
//-----------------------------------------------------------------------------
module mac #(
    parameter DATA_W = 32
) (
    // Clock / reset
    input  wire              i_clk,        // primary clock (rising-edge)
    input  wire              i_rstn,       // async active-low reset

    // Data inputs
    input  wire [DATA_W-1:0] i_data,       // incoming data word
    input  wire [DATA_W-1:0] i_weight,     // stationary weight
    input  wire [DATA_W-1:0] i_pre_result, // partial sum from cell above

    // Data outputs
    output reg  [DATA_W-1:0] o_result,     // registered MAC result (1-cyc latency)
    output reg  [DATA_W-1:0] o_data_next   // registered data forward (1-cyc latency)
);

    // MAC next-value: 32-bit multiply truncated to DATA_W bits, then 32-bit
    // accumulate that wraps modulo 2^DATA_W (no saturation). The DATA_W-wide
    // intermediate makes the truncate/wrap explicit per mac.md S4.
    wire [DATA_W-1:0] mac_result_next;

    assign mac_result_next = (i_data * i_weight) + i_pre_result;

    // Registered MAC result (CHK-MAC-01/03/04/05/06)
    always @(posedge i_clk or negedge i_rstn) begin
        if (!i_rstn) begin
            o_result <= {DATA_W{1'b0}};
        end
        else begin
            o_result <= mac_result_next;
        end
    end

    // Registered data forward to the next cell in the row (CHK-MAC-02/07)
    always @(posedge i_clk or negedge i_rstn) begin
        if (!i_rstn) begin
            o_data_next <= {DATA_W{1'b0}};
        end
        else begin
            o_data_next <= i_data;
        end
    end

endmodule
