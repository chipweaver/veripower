`timescale 1ns/1ps
module power_probe;
  reg clk=0, rst_n=0, enabled=1, qkv_in_valid=0, causal_en=0, o_out_ready=1;
  reg [63:0] qkv_in_data=0;
  wire [63:0] o_out_data;
  wire qkv_in_ready, o_out_valid, busy, done;
  fa_core measured_device(.*);
  always #5 if(enabled) clk=~clk;
  import "DPI-C" function void fa_ref_set_input(input int idx, input int bits);
  import "DPI-C" function void fa_ref_compute(input int causal);
  import "DPI-C" function real fa_ref_get_output(input int idx);
  string scenario, saif, status;
  integer fd, edges=0, begin_edges, outputs=0;
  bit measuring=0;
  always @(posedge clk) if(measuring) edges++;
  initial begin #1000000; $fatal(1,"experiment timeout"); end
  task tile(input bit causal);
    causal_en=causal;
    for(int i=0;i<48;i++) fa_ref_set_input(i, i<32 ? 0 : 'h3c00);
    fa_ref_compute(causal);
    fork
      begin
        for(int i=0;i<12;i++) begin
          @(negedge clk);
          qkv_in_data=i<8 ? 64'b0 : 64'h3c003c003c003c00;
          qkv_in_valid=1;
          do @(posedge clk); while(qkv_in_ready!==1);
        end
        @(negedge clk); qkv_in_valid=0;
      end
      begin
        for(int row=0;row<4;row++) begin
          // Sample stable data before its accepting edge; avoid RTL-only #1ps observations.
          do @(negedge clk); while(o_out_valid!==1);
          for(int lane=0;lane<4;lane++) begin
            if(fa_ref_get_output(row*4+lane)!=1.0 || o_out_data[lane*16+:16]!==16'h3c00)
              $fatal(1,"output mismatch causal=%0d row=%0d data=%h",causal,row,o_out_data);
          end
          @(posedge clk); outputs+=4;
        end
      end
    join
    do @(negedge clk); while(busy!==0);
  endtask
  initial begin
    if(!$value$plusargs("CASE=%s",scenario) || !$value$plusargs("SAIF=%s",saif) || !$value$plusargs("STATUS=%s",status)) $fatal(1,"missing args");
    repeat(6) @(negedge clk);
    if(scenario=="active") begin rst_n=1; repeat(4) @(negedge clk); end
    else if(scenario=="stopped") enabled=0;
    else if(scenario!="clocked") $fatal(1,"unknown scenario");
    #0.001;
    $set_gate_level_monitoring("on"); $set_toggle_region(power_probe.measured_device);
    measuring=1; begin_edges=edges; $toggle_start;
    if(scenario=="active") begin tile(0); tile(1); if(outputs!=32) $fatal(1,"missing outputs"); end
    else begin
      #1000;
      if(rst_n!==0 || busy!==0 || o_out_valid!==0) $fatal(1,"reset state violated");
      if(scenario=="stopped" && edges!=begin_edges) $fatal(1,"clock did not stop");
      if(scenario=="clocked" && edges-begin_edges!=100) $fatal(1,"clock count mismatch");
    end
    $toggle_stop; measuring=0;
    $toggle_report(saif,1.0e-9,"power_probe.measured_device");
    $display("EXPERIMENT_PASS case=%s outputs=%0d clock_edges=%0d",scenario,outputs,edges-begin_edges);
    fd=$fopen(status,"w"); if(!fd) $fatal(1,"status open failed"); $fdisplay(fd,"PASS");$fclose(fd);$finish;
  end
endmodule
