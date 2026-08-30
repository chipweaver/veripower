//======================================================================
// Module      : systolic_reg
// Description : Systolic input-skew aligner (F-02) for the 2x2
//               weight-stationary MAC array. Produces the staggered
//               diagonal wavefront the array expects:
//                 out1 = in1 delayed 1 cycle  (register delay10)
//                 out2 = in2 delayed 2 cycles (registers delay20->delay21)
//               Pure delay-line: no control, no back-pressure, no
//               handshake. Async active-low reset clears all skew
//               registers to 0.
// Author      : VeriPower rtl-design
// Created     : 2026-06-17
// Version     : 0.1
//======================================================================
module systolic_reg #(
    parameter DATA_W = 32
) (
    // clock / reset
    input  wire              i_clk,   // single clock; all registers update on rising edge
    input  wire              i_rstn,  // async active-low reset (negedge i_rstn)

    // data inputs
    input  wire [DATA_W-1:0] in1,     // input stream 1 (systolic_in1 = fifo_00.o_data)
    input  wire [DATA_W-1:0] in2,     // input stream 2 (systolic_in2 = fifo_01.o_data)

    // data outputs
    output wire [DATA_W-1:0] out1,    // in1 delayed 1 cycle  -> mac00_in (mac_00.i_data)
    output wire [DATA_W-1:0] out2     // in2 delayed 2 cycles -> mac10_in (mac_10.i_data)
);

    // Skew delay registers
    reg [DATA_W-1:0] delay10;  // 1-cycle line  : delay10 <= in1
    reg [DATA_W-1:0] delay20;  // 2-cycle line s1: delay20 <= in2
    reg [DATA_W-1:0] delay21;  // 2-cycle line s2: delay21 <= delay20

    // 1-cycle delay line: in1 -> out1
    always @(posedge i_clk or negedge i_rstn) begin
        if (!i_rstn) begin
            delay10 <= {DATA_W{1'b0}};
        end
        else begin
            delay10 <= in1;
        end
    end

    // 2-cycle delay line: in2 -> delay20 -> delay21 -> out2
    always @(posedge i_clk or negedge i_rstn) begin
        if (!i_rstn) begin
            delay20 <= {DATA_W{1'b0}};
            delay21 <= {DATA_W{1'b0}};
        end
        else begin
            delay20 <= in2;
            delay21 <= delay20;
        end
    end

    assign out1 = delay10;
    assign out2 = delay21;

endmodule
