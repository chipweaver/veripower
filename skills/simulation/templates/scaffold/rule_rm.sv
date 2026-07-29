// Rule-based reference model: {{RM_NAME}}.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
{{RM_IMP_DECL_MACROS}}
class {{MODULE}}_{{RM_NAME}} extends uvm_component;
  `uvm_component_utils({{MODULE}}_{{RM_NAME}})

{{RM_ANALYSIS_IMPS}}

  // TODO(rm): Add internal state mirrors from this testpoint's inlined_check_hints[].reference_rule
  // in scaffold-specification.json — materialize-scaffold already put the value there.

  function new(string name = "{{MODULE}}_{{RM_NAME}}", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
{{RM_ANALYSIS_IMP_NEWS}}
    reset();
  endfunction

{{RM_WRITE_FUNCTIONS}}

  // NOTE: This RM uses Pattern B (poll-style: scoreboard calls predict()).
  // For streaming/pipelined predictions, switch to Pattern A:
  //   declare `uvm_analysis_port #(<obs_txn>) ap_predict;` and call
  //   ap_predict.write(predicted) from your write_<inport>() handler.
  // CONVENTION: one write_<inport>() per rm.inports[] entry; update internal state, predict the observed txn.
  // TODO(rm): Implement prediction — parse inport txn, update state, produce expected output.
  virtual function {{MODULE}}_{{OBS_AGENT}}_txn predict();
    {{MODULE}}_{{OBS_AGENT}}_txn expected;
    expected = {{MODULE}}_{{OBS_AGENT}}_txn::type_id::create("expected");
    // ← Fill prediction logic here.
    return expected;
  endfunction

  // TODO(rm): Reset internal state to power-on values from this testpoint's
  // inlined_check_hints[].reset_behavior in scaffold-specification.json.
  virtual function void reset();
    // ← Initialize all internal state mirrors.
  endfunction
endclass
