// Agent assembly for {{AGENT_NAME}}.
// Generated from scaffold-spec.json. Typically nothing to fill — fully assembled.
class {{MODULE}}_{{AGENT_NAME}}_agent extends uvm_agent;
  `uvm_component_utils({{MODULE}}_{{AGENT_NAME}}_agent)

  {{MODULE}}_{{AGENT_NAME}}_driver  m_driver;
  {{MODULE}}_{{AGENT_NAME}}_monitor m_monitor;
  uvm_sequencer #({{MODULE}}_{{AGENT_NAME}}_txn) m_sequencer;

  uvm_analysis_port #({{MODULE}}_{{AGENT_NAME}}_txn) ap;

  function new(string name = "{{MODULE}}_{{AGENT_NAME}}_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    ap = new("ap", this);
    if (get_is_active() == UVM_ACTIVE) begin
      m_driver    = {{MODULE}}_{{AGENT_NAME}}_driver::type_id::create("m_driver", this);
      m_sequencer = uvm_sequencer #({{MODULE}}_{{AGENT_NAME}}_txn)::type_id::create("m_sequencer", this);
    end
    m_monitor = {{MODULE}}_{{AGENT_NAME}}_monitor::type_id::create("m_monitor", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    if (get_is_active() == UVM_ACTIVE)
      m_driver.seq_item_port.connect(m_sequencer.seq_item_export);
    m_monitor.ap.connect(ap);
  endfunction
endclass
