//==============================================================================
// Module      : tpu_top
// Description : Top integration of the 2x2 weight-stationary systolic-array
//               integer matrix-multiply accelerator. Instantiates the leaf
//               children (4x mac, 1x systolic_reg, 3x fifo) and wires them per
//               design.md s1.4.2, and implements inline the APB-style register
//               file (F-04), the start/counter control FSM (F-05), the
//               counter-routed result mux, and done generation.
// Author      : VeriPower rtl-design (tpu_top child)
// Created     : 2026-06-17
// Version     : 0.1
//==============================================================================
module tpu_top #(
    parameter DATA_W    = 32,  // data / weight / accumulator width
    parameter APB_ADDR_W = 32, // APB address bus width
    parameter CNT_W     = 4    // control counter width
) (
    // clock / reset
    input  wire                   i_clk,      // single clock, posedge
    input  wire                   i_rstn,     // async active-low reset

    // data_in
    input  wire [DATA_W-1:0]      in1,        // stream 1 -> fifo_00
    input  wire [DATA_W-1:0]      in2,        // stream 2 -> fifo_01
    input  wire                   in1_en,     // fifo_00 write enable
    input  wire                   in2_en,     // fifo_01 write enable

    // ctrl
    input  wire                   start,      // launch compute pass / gate counter
    output wire [CNT_W-1:0]       counter,    // exposed 4-bit counter

    // status
    output wire [2:0]             o_full,     // {fifo_result,fifo_01,fifo_00}
    output wire [2:0]             o_empty,    // {fifo_result,fifo_01,fifo_00}
    output wire                   done,       // counter >= 5

    // apb (APB-style register port)
    input  wire [APB_ADDR_W-1:0]  i_paddr,    // register address
    input  wire                   i_psel,     // APB select
    input  wire                   i_pwrite,   // 1=write 0=read
    input  wire [DATA_W-1:0]      i_pwdata,   // write data
    input  wire                   i_penable,  // APB enable phase
    output reg  [DATA_W-1:0]      o_prdata    // read data (result-FIFO / 0)
);

    //--------------------------------------------------------------------------
    // Internal cross-module nets (design.md s1.4.2 cut-edges)
    //--------------------------------------------------------------------------
    // input FIFO read data -> systolic_reg
    wire [DATA_W-1:0] systolic_in1;   // fifo_00.o_data -> systolic_reg.in1
    wire [DATA_W-1:0] systolic_in2;   // fifo_01.o_data -> systolic_reg.in2

    // systolic_reg skewed outputs -> top-row mac i_data
    wire [DATA_W-1:0] mac00_in;       // systolic_reg.out1 -> mac_00.i_data
    wire [DATA_W-1:0] mac10_in;       // systolic_reg.out2 -> mac_10.i_data

    // mac data-forward nets (row data ripple)
    wire [DATA_W-1:0] mac01_in;       // mac_00.o_data_next -> mac_01.i_data
    wire [DATA_W-1:0] mac11_in;       // mac_10.o_data_next -> mac_11.i_data

    // mac column partial-sum nets
    wire [DATA_W-1:0] mac00_out;      // mac_00.o_result -> mac_10.i_pre_result
    wire [DATA_W-1:0] mac01_out;      // mac_01.o_result -> mac_11.i_pre_result

    // bottom-row mac results -> parent result mux
    wire [DATA_W-1:0] out1;           // mac_10.o_result (result word A)
    wire [DATA_W-1:0] out2;           // mac_11.o_result (result word B)

    // result FIFO data path
    wire [DATA_W-1:0] result_fifo_o_data;  // fifo_result.o_data -> APB read mux
    reg  [DATA_W-1:0] result_fifo_i_data;  // parent result mux -> fifo_result.i_data

    // intentionally-unconnected mac data-forward outputs (right column)
    wire [DATA_W-1:0] mac01_data_next_nc;  // mac_01.o_data_next (no consumer)
    wire [DATA_W-1:0] mac11_data_next_nc;  // mac_11.o_data_next (no consumer)

    // per-instance FIFO status flags (composed into the 3-bit top buses)
    wire fifo00_full;
    wire fifo01_full;
    wire fifo_result_full;
    wire fifo00_empty;
    wire fifo01_empty;
    wire fifo_result_empty;

    //--------------------------------------------------------------------------
    // Inline control strobes (F-04 / F-05) -- combinational
    //--------------------------------------------------------------------------
    reg  [CNT_W-1:0] counter_r;       // 4-bit control counter (F-05)

    wire write_enb;                   // APB write strobe (F-04)
    wire read_enb;                    // APB read strobe  (F-04)
    wire fifo_en;                     // input-FIFO pop enable (F-05)
    wire result_fifo_wr;             // result-FIFO write enable (F-05)

    // APB-style decoded enables
    assign write_enb = i_psel & i_penable &  i_pwrite;
    assign read_enb  = i_psel & i_penable & ~i_pwrite;

    // F-05 control terms
    assign fifo_en        = start & (counter_r < 4'd2);
    assign result_fifo_wr = (counter_r >= 4'd2) & (counter_r <= 4'd5);
    assign done           = (counter_r >= 4'd5);
    assign counter        = counter_r;

    //--------------------------------------------------------------------------
    // APB-style register file weights (F-04). Clocked-only, NO reset on this
    // block -- faithful to the reference; i_rstn does NOT clear mem.
    //--------------------------------------------------------------------------
    reg [DATA_W-1:0] mem [0:3];       // W00=0, W01=1, W10=2, W11=3

    always @(posedge i_clk) begin
        if (write_enb) begin
            mem[i_paddr] <= i_pwdata;
        end
    end

    // APB read path (combinational): result-FIFO o_data on read, else 0.
    always @(*) begin
        if (read_enb) begin
            o_prdata = result_fifo_o_data;
        end
        else begin
            o_prdata = {DATA_W{1'b0}};
        end
    end

    //--------------------------------------------------------------------------
    // Start/counter control FSM (F-05). Async reset -> 0; increment while
    // start, reset to 0 when start deasserted.
    //--------------------------------------------------------------------------
    always @(posedge i_clk or negedge i_rstn) begin
        if (!i_rstn) begin
            counter_r <= {CNT_W{1'b0}};
        end
        else if (start) begin
            counter_r <= counter_r + 4'd1;
        end
        else begin
            counter_r <= {CNT_W{1'b0}};
        end
    end

    //--------------------------------------------------------------------------
    // Counter-routed result mux (F-05): out1 at counter in {2,4},
    // out2 at counter in {3,5}, else 0.
    //--------------------------------------------------------------------------
    always @(*) begin
        case (counter_r)
            4'd2:    result_fifo_i_data = out1;
            4'd4:    result_fifo_i_data = out1;
            4'd3:    result_fifo_i_data = out2;
            4'd5:    result_fifo_i_data = out2;
            default: result_fifo_i_data = {DATA_W{1'b0}};
        endcase
    end

    //--------------------------------------------------------------------------
    // Status bus aggregation: {fifo_result, fifo_01, fifo_00} = [2],[1],[0]
    //--------------------------------------------------------------------------
    assign o_full  = {fifo_result_full,  fifo01_full,  fifo00_full};
    assign o_empty = {fifo_result_empty, fifo01_empty, fifo00_empty};

    //==========================================================================
    // Leaf instantiations
    //==========================================================================

    //----- Input FIFOs --------------------------------------------------------
    fifo fifo_00 (
        .i_clk   (i_clk),
        .i_rstn  (i_rstn),
        .i_wr    (in1_en),
        .i_rd    (fifo_en),
        .i_data  (in1),
        .o_data  (systolic_in1),
        .o_full  (fifo00_full),
        .o_empty (fifo00_empty)
    );

    fifo fifo_01 (
        .i_clk   (i_clk),
        .i_rstn  (i_rstn),
        .i_wr    (in2_en),
        .i_rd    (fifo_en),
        .i_data  (in2),
        .o_data  (systolic_in2),
        .o_full  (fifo01_full),
        .o_empty (fifo01_empty)
    );

    //----- Result FIFO --------------------------------------------------------
    fifo fifo_result (
        .i_clk   (i_clk),
        .i_rstn  (i_rstn),
        .i_wr    (result_fifo_wr),
        .i_rd    (read_enb),
        .i_data  (result_fifo_i_data),
        .o_data  (result_fifo_o_data),
        .o_full  (fifo_result_full),
        .o_empty (fifo_result_empty)
    );

    //----- Systolic skew aligner ---------------------------------------------
    systolic_reg systolic_reg (
        .i_clk  (i_clk),
        .i_rstn (i_rstn),
        .in1    (systolic_in1),
        .in2    (systolic_in2),
        .out1   (mac00_in),
        .out2   (mac10_in)
    );

    //----- 2x2 MAC array ------------------------------------------------------
    // Top row (mac_00, mac_01): i_pre_result tied to 32'h0 (pure multiply).
    mac mac_00 (
        .i_clk        (i_clk),
        .i_rstn       (i_rstn),
        .i_data       (mac00_in),
        .i_weight     (mem[0]),
        .i_pre_result (32'h0),
        .o_result     (mac00_out),
        .o_data_next  (mac01_in)
    );

    mac mac_01 (
        .i_clk        (i_clk),
        .i_rstn       (i_rstn),
        .i_data       (mac01_in),
        .i_weight     (mem[1]),
        .i_pre_result (32'h0),
        .o_result     (mac01_out),
        .o_data_next  (mac01_data_next_nc)  // intentionally unconnected
    );

    // Bottom row (mac_10, mac_11): i_pre_result = top-row column partial sum.
    mac mac_10 (
        .i_clk        (i_clk),
        .i_rstn       (i_rstn),
        .i_data       (mac10_in),
        .i_weight     (mem[2]),
        .i_pre_result (mac00_out),
        .o_result     (out1),
        .o_data_next  (mac11_in)
    );

    mac mac_11 (
        .i_clk        (i_clk),
        .i_rstn       (i_rstn),
        .i_data       (mac11_in),
        .i_weight     (mem[3]),
        .i_pre_result (mac01_out),
        .o_result     (out2),
        .o_data_next  (mac11_data_next_nc)  // intentionally unconnected
    );

endmodule
