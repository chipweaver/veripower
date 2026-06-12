// Sequence: {{SEQ_NAME}} (agent: {{AGENT_NAME}}).
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
// Description: {{SEQ_DESC}}
class {{MODULE}}_{{SEQ_NAME}}_seq extends {{MODULE}}_base_seq;
  `uvm_object_utils({{MODULE}}_{{SEQ_NAME}}_seq)

  function new(string name = "{{MODULE}}_{{SEQ_NAME}}_seq");
    super.new(name);
  endfunction

  // CONVENTION: build/randomize txns of type <module>_<agent>_txn and send via the agent's m_sequencer.
  // TODO(sequence): Implement stimulus pattern — {{SEQ_DESC}}.
  task body();
    {{MODULE}}_{{AGENT_NAME}}_txn txn;
    // ← Create, randomize, and send transactions here.
    // txn = {{MODULE}}_{{AGENT_NAME}}_txn::type_id::create("txn");
    // start_item(txn);
    // assert(txn.randomize() with { ... });
    // finish_item(txn);
  endtask
endclass
