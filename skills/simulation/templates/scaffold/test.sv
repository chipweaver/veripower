// Test: {{TEST_NAME}} — Feature: {{FEATURE}}.
// Generated from scaffold-spec.json.
class {{MODULE}}_{{TEST_NAME}}_test extends {{MODULE}}_base_test;
  `uvm_component_utils({{MODULE}}_{{TEST_NAME}}_test)

  function new(string name = "{{MODULE}}_{{TEST_NAME}}_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "{{TEST_ID}}";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
{{SEQ_START_CALLS}}
    phase.drop_objection(this);
  endtask
endclass
