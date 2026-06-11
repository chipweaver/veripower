class MY_MODULE_base_test extends uvm_test;
  `uvm_component_utils(MY_MODULE_base_test)

  MY_MODULE_env m_env;
  string m_test_id;

  function new(string name = "MY_MODULE_base_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "unassigned";
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    m_env = MY_MODULE_env::type_id::create("m_env", this);
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    `uvm_info(get_type_name(), $sformatf("Running derived test_id=%0s", m_test_id), UVM_LOW)
    #1ns;
    phase.drop_objection(this);
  endtask

  function void report_phase(uvm_phase phase);
    uvm_report_server server;
    int severity_count;
    int fh;
    string status_path;
    string status_token;
    super.report_phase(phase);
    server = uvm_report_server::get_server();
    severity_count = server.get_severity_count(UVM_FATAL) + server.get_severity_count(UVM_ERROR);
    status_token = (severity_count == 0) ? "PASS" : "FAIL";
    `uvm_info(get_type_name(),
              $sformatf("TEST CASE %s test_id=%s fatal_or_error=%0d",
                        status_token, m_test_id, severity_count),
              UVM_LOW)
    // Write a per-test status file (one-token PASS/FAIL) — consumed by
    // run_vcs_regression.sh as the pass/fail contract. Replaces the prior
    // log-scrape for "TEST CASE PASSED".
    if ($value$plusargs("IPD_STATUS_PATH=%s", status_path)) begin
      fh = $fopen(status_path, "w");
      if (fh != 0) begin
        $fdisplay(fh, "%s", status_token);
        $fclose(fh);
      end
    end
  endfunction
endclass
