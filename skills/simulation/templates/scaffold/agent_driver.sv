// Driver for {{AGENT_NAME}} agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
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

  // CONVENTION: `vif` is this agent's virtual interface — tb_top registers it in config_db under key "<agent>_vif"; drive the DUT via `vif` per timing protocol, pull items from seq_item_port.
  // TODO(driver): Drive DUT signals via virtual interface per timing protocol.
  virtual task drive_txn({{MODULE}}_{{AGENT_NAME}}_txn txn);
    @(posedge vif.clk);
    // ← Fill signal assignments here.
  endtask
endclass
