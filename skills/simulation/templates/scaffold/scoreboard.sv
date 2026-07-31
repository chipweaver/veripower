// Scoreboard: {{SB_NAME}}.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class {{MODULE}}_{{SB_NAME}} extends uvm_scoreboard;
  `uvm_component_utils({{MODULE}}_{{SB_NAME}})

  uvm_analysis_imp #({{MODULE}}_{{OBS_AGENT}}_txn, {{MODULE}}_{{SB_NAME}}) analysis_export;
  {{MODULE}}_{{RM_NAME}} rm;

  int unsigned pass_count;
  int unsigned fail_count;

  function new(string name = "{{MODULE}}_{{SB_NAME}}", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    analysis_export = new("analysis_export", this);
    rm = {{MODULE}}_{{RM_NAME}}::type_id::create("rm", this);
    pass_count = 0;
    fail_count = 0;
  endfunction

  // The RM must see this transaction before predict() is asked about it, which is why the
  // forward happens here rather than through an analysis connection: inside one component
  // the order is yours, across a fanout it is not.
  // TODO(scoreboard): forward txn into the RM (rm.write_<inport>(txn)) before comparing.
  virtual function void write({{MODULE}}_{{OBS_AGENT}}_txn txn);
    check_txn(txn);
  endfunction

  // CONVENTION: compares the observer agent's txn (scoreboard.observer names the agent) against the RM prediction; increment a real mismatch counter (uvm_error, never $fatal).
  // TODO(scoreboard): Compare observed txn against RM prediction.
  virtual function void check_txn({{MODULE}}_{{OBS_AGENT}}_txn txn);
    {{MODULE}}_{{OBS_AGENT}}_txn expected = rm.predict();
    // ← Fill comparison logic; increment pass_count or fail_count.
  endfunction

  function void report_phase(uvm_phase phase);
    `uvm_info(get_type_name(),
      $sformatf("Scoreboard summary: PASS=%0d FAIL=%0d", pass_count, fail_count), UVM_LOW)
    if (fail_count > 0)
      `uvm_error(get_type_name(),
        $sformatf("Scoreboard detected %0d mismatch(es)", fail_count))
  endfunction
endclass
