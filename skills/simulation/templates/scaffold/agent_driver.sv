// Driver for {{AGENT_NAME}} agent.
// Generated from the simulation-plan sidecars and specification boundary. Fill domain-labeled stubs per verification-plan.md test strategy.
class {{MODULE}}_{{AGENT_NAME}}_driver extends uvm_driver #({{MODULE}}_{{AGENT_NAME}}_txn);
  `uvm_component_utils({{MODULE}}_{{AGENT_NAME}}_driver)

  virtual {{MODULE}}_{{AGENT_NAME}}_if vif;

  function new(string name = "{{MODULE}}_{{AGENT_NAME}}_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual {{MODULE}}_{{AGENT_NAME}}_if)::get(this, "", "{{AGENT_NAME}}_vif", vif))
      `uvm_fatal(get_type_name(), "Virtual interface not found in config_db")
  endfunction

  task run_phase(uvm_phase phase);
    {{MODULE}}_{{AGENT_NAME}}_txn txn;
    forever begin
      seq_item_port.get_next_item(txn);
      drive_txn(txn);
      seq_item_port.item_done();
    end
  endtask

{{DRIVER_TASK_NOTE}}
  virtual task drive_txn({{MODULE}}_{{AGENT_NAME}}_txn txn);
    `uvm_fatal("UNIMPLEMENTED_DRIVER", "Implement drive_txn before driving transactions")
  endtask
endclass
