// Transaction for {{AGENT_NAME}} agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class {{MODULE}}_{{AGENT_NAME}}_txn extends uvm_sequence_item;
  `uvm_object_utils_begin({{MODULE}}_{{AGENT_NAME}}_txn)
{{FIELD_MACROS}}
  `uvm_object_utils_end

{{FIELD_DECLARATIONS}}

  // TODO(transaction): Add constraints.

  function new(string name = "{{MODULE}}_{{AGENT_NAME}}_txn");
    super.new(name);
  endfunction

  virtual function string convert2string();
    // TODO(transaction): Format all fields for debug display.
    return $sformatf("{{AGENT_NAME}}_txn");
  endfunction
endclass
