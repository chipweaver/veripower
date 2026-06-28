// Monitor for {{AGENT_NAME}} agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class {{MODULE}}_{{AGENT_NAME}}_monitor extends uvm_monitor;
  `uvm_component_utils({{MODULE}}_{{AGENT_NAME}}_monitor)

  uvm_analysis_port #({{MODULE}}_{{AGENT_NAME}}_txn) ap;
  virtual {{MODULE}}_{{AGENT_NAME}}_if vif;

  function new(string name = "{{MODULE}}_{{AGENT_NAME}}_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    ap = new("ap", this);
    if (!uvm_config_db#(virtual {{MODULE}}_{{AGENT_NAME}}_if)::get(this, "", "{{AGENT_NAME}}_vif", vif))
      `uvm_fatal(get_type_name(), "Virtual interface not found in config_db")
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      {{MODULE}}_{{AGENT_NAME}}_txn txn;
      txn = {{MODULE}}_{{AGENT_NAME}}_txn::type_id::create("txn");
      sample_txn(txn);
      ap.write(txn);
    end
  endtask

  // CONVENTION: `vif` is this agent's virtual interface (tb_top registers it in config_db under key "<agent>_vif"); sample DUT outputs via `vif`, publish observed txns on analysis port 'ap'.
  // TODO(monitor): Sample DUT outputs via virtual interface.
  virtual task sample_txn({{MODULE}}_{{AGENT_NAME}}_txn txn);
    @(posedge vif.clk);
    // ← Fill signal sampling here.
  endtask
endclass
