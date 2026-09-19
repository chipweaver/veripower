`timescale 1ns/1ps
module power_probe;
  reg clk=0, resetn=0, start=0, enabled=1, sample_mode=0;
  reg [4:0] token_in=0, pos_in=0;
  reg signed [15:0] inv_temp=2926;
  reg [31:0] rng_in=0;
  wire busy, done;
  wire [4:0] next_token;
  wire [31:0] rng_out;
  microgpt_core measured_device(.*);
  always #6.25 if(enabled) clk=~clk;
  import "DPI-C" function void mgpt_rm_reset();
  import "DPI-C" function void mgpt_rm_step(input int token,pos,mode,temp,rng,output int nt,nr);
  string scenario, saif, status;
  integer fd, edges=0, begin_edges, checked=0, nt,nr;
  bit measuring=0;
  always @(posedge clk) if(measuring) edges++;
  initial begin #1000000; $fatal(1,"experiment timeout"); end
  initial begin
    if(!$value$plusargs("CASE=%s",scenario) || !$value$plusargs("SAIF=%s",saif) || !$value$plusargs("STATUS=%s",status)) $fatal(1,"missing args");
    repeat(6) @(negedge clk);
    if(scenario=="active") begin resetn=1; repeat(4) @(negedge clk); end
    else if(scenario=="stopped") enabled=0;
    else if(scenario!="clocked") $fatal(1,"unknown scenario");
    #0.001;
    mgpt_rm_reset();
    $set_gate_level_monitoring("on"); $set_toggle_region(power_probe.measured_device);
    measuring=1; begin_edges=edges; $toggle_start;
    if(scenario=="active") begin
      for(int pos=0;pos<3;pos++) begin
        mgpt_rm_step(token_in,pos,0,inv_temp,rng_in,nt,nr);
        @(negedge clk); pos_in=pos; start=1;
        @(negedge clk); start=0;
        do @(negedge clk); while(done!==1);
        if(next_token!==nt[4:0] || rng_out!==nr) $fatal(1,"token mismatch pos=%0d got=%0d expected=%0d rng=%h/%h",pos,next_token,nt,rng_out,nr);
        token_in=next_token; rng_in=rng_out; checked++;
        do @(negedge clk); while(busy!==0);
      end
    end else begin
      #1000;
      if(resetn!==0 || busy!==0 || done!==0) $fatal(1,"reset state violated");
      if(scenario=="stopped" && edges!=begin_edges) $fatal(1,"clock did not stop");
      if(scenario=="clocked" && edges-begin_edges!=80) $fatal(1,"clock count mismatch");
    end
    $toggle_stop; measuring=0;
    $toggle_report(saif,1.0e-9,"power_probe.measured_device");
    $display("EXPERIMENT_PASS case=%s checked=%0d clock_edges=%0d",scenario,checked,edges-begin_edges);
    fd=$fopen(status,"w");if(!fd) $fatal(1,"status open failed");$fdisplay(fd,"PASS");$fclose(fd);$finish;
  end
endmodule
