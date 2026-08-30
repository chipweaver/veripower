//============================================================================
// Module      : fifo
// Description : 8-entry x 32-bit pointer-based single-clock FIFO with a
//               combinational read path (feature F-03). Synchronous write
//               gated by !o_full; read pointer advances on !o_empty; the
//               output word is purely combinational (o_data = mem[rd_addr]).
//               Empty/full are derived from 3-bit (modulo-8) pointer compare;
//               full reserves one slot ((wr_addr+1)==rd_addr). Async
//               active-low reset clears memory and both pointers to 0.
//               Instantiated 3x by tpu_top (fifo_00/fifo_01/fifo_result);
//               the parent aggregates per-instance o_full/o_empty into the
//               top-level 3-bit status buses.
// Author      : VeriPower rtl-design
// Created     : 2026-06-17
// Version     : 0.1
//============================================================================
module fifo (
    // clock / reset
    input  wire        i_clk,    // single clock domain
    input  wire        i_rstn,   // async active-low reset

    // write side
    input  wire        i_wr,     // write request; write on i_wr & !o_full
    input  wire [31:0] i_data,   // write data sampled at the write edge

    // read side
    input  wire        i_rd,     // read request; pop on i_rd & !o_empty
    output wire [31:0] o_data,   // combinational read of mem[rd_addr]

    // status
    output wire        o_full,   // (wr_addr + 1) == rd_addr (one slot reserved)
    output wire        o_empty   // wr_addr == rd_addr
);

    // Sized from the fixed 8x32 contract (fifo.md S1: no parameterization);
    // localparams only name the magic-number widths, they are not overridable.
    localparam DEPTH  = 8;            // physical entries
    localparam DATA_W = 32;           // word width
    localparam ADDR_W = 3;            // 3-bit pointers => modulo-8 wrap

    // State elements
    reg [DATA_W-1:0] mem [0:DEPTH-1]; // 8 x 32 register array
    reg [ADDR_W-1:0] wr_addr;         // write pointer (modulo-8)
    reg [ADDR_W-1:0] rd_addr;         // read pointer  (modulo-8)

    integer index;                    // reset clear loop variable

    // Status flags: combinational pointer compare with 3-bit modulo-8 wrap.
    assign o_empty = (wr_addr == rd_addr);
    assign o_full  = ((wr_addr + 1'b1) == rd_addr);

    // Combinational read: output tracks the current read-pointer location with
    // no register delay (F-03 / CHK-FIFO-03). Consumers must gate on o_empty.
    assign o_data  = mem[rd_addr];

    // Write port + write pointer: synchronous, gated by !o_full. A write while
    // full is ignored and wr_addr does not advance (CHK-FIFO-01/09).
    always @(posedge i_clk or negedge i_rstn) begin
        if (!i_rstn) begin
            for (index = 0; index < DEPTH; index = index + 1) begin : rst_mem
                mem[index] <= {DATA_W{1'b0}};
            end
            wr_addr <= {ADDR_W{1'b0}};
        end
        else if (i_wr && !o_full) begin
            mem[wr_addr] <= i_data;
            wr_addr      <= wr_addr + 1'b1;
        end
    end

    // Read pointer: advances on i_rd & !o_empty. A read while empty is ignored
    // and rd_addr does not advance (CHK-FIFO-02/09).
    always @(posedge i_clk or negedge i_rstn) begin
        if (!i_rstn) begin
            rd_addr <= {ADDR_W{1'b0}};
        end
        else if (i_rd && !o_empty) begin
            rd_addr <= rd_addr + 1'b1;
        end
    end

endmodule
