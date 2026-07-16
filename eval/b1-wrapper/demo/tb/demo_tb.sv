// demo_tb.sv — minimal UVM testbench for accum (generic demo).
// Pass/fail signal = UVM error count (uvm_report_server), the standard UVM
// convention; NO VeriPower status-file contract. Replace with your own TB.
`include "uvm_macros.svh"
import uvm_pkg::*;

module demo_tb_top;
    reg clk = 0, rst_n = 0, en = 0;
    reg  [7:0] din = 0;
    wire [7:0] sum;
    accum dut (.clk(clk), .rst_n(rst_n), .en(en), .din(din), .sum(sum));
    always #5 clk = ~clk;

    class demo_test extends uvm_test;
        `uvm_component_utils(demo_test)
        function new(string name, uvm_component parent); super.new(name, parent); endfunction
        task run_phase(uvm_phase phase);
            phase.raise_objection(this);
            @(negedge clk); rst_n = 0; en = 0; din = 0;
            repeat (2) @(negedge clk); rst_n = 1;
            en = 1; din = 8'd3; @(negedge clk);
            din = 8'd4; @(negedge clk);
            en = 0; @(negedge clk);
            if (sum !== 8'd7)
                `uvm_error("DEMO", $sformatf("expected sum=7, got %0d", sum))
            else
                `uvm_info("DEMO", "accumulator check passed", UVM_LOW)
            phase.drop_objection(this);
        endtask
    endclass

    initial run_test("demo_test");
endmodule
