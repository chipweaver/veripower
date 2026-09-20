// Testbench top for {{TOP}}.
// Generated from the simulation-plan sidecars and specification boundary and rewritten every round — everything here is derived
// from the plan and boundary. Clock observation connections and reset sequencing are authored includes.
module {{TOP}}_tb_top;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  import {{MODULE}}_tb_pkg::*;

  // --- Top-level controls ---
{{CLOCK_DECLS}}
{{RESET_DECLS}}
{{CLOCK_GENS}}
{{IF_INSTANTIATIONS}}
  `include "{{MODULE}}_clocks.svh"

  // --- Reset schedule ---
  // Included after the interfaces so reset can be timed against observed traffic.
  `include "{{MODULE}}_reset.svh"

  // --- DUT instantiation ---
  {{TOP}} u_dut(
{{DUT_CONNECTIONS}}
  );

  // --- UVM config_db & test launch ---
  initial begin
    uvm_root root;
    uvm_report_server server;
    string status_path;
    int fh;
{{CONFIG_DB_SETS}}
    root = uvm_root::get();
    root.finish_on_completion = 0;
    run_test();
    server = uvm_report_server::get_server();
    if ($value$plusargs("IPD_STATUS_PATH=%s", status_path)) begin
      fh = $fopen(status_path, "w");
      if (fh == 0) $fatal(1, "Cannot write test status: %s", status_path);
      $fdisplay(fh, "%s", (server.get_severity_count(UVM_FATAL) == 0 &&
                           server.get_severity_count(UVM_ERROR) == 0) ? "PASS" : "FAIL");
      $fclose(fh);
    end
    $finish;
  end
endmodule
