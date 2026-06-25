// Agent assembly for data_in.
// Generated from scaffold-spec.json. Typically nothing to fill — fully assembled.
class tpu_top_data_in_agent extends uvm_agent;
  `uvm_component_utils(tpu_top_data_in_agent)

  tpu_top_data_in_driver  m_driver;
  tpu_top_data_in_monitor m_monitor;
  uvm_sequencer #(tpu_top_data_in_txn) m_sequencer;

  uvm_analysis_port #(tpu_top_data_in_txn) ap;

  function new(string name = "tpu_top_data_in_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    ap = new("ap", this);
    if (get_is_active() == UVM_ACTIVE) begin
      m_driver    = tpu_top_data_in_driver::type_id::create("m_driver", this);
      m_sequencer = uvm_sequencer #(tpu_top_data_in_txn)::type_id::create("m_sequencer", this);
    end
    m_monitor = tpu_top_data_in_monitor::type_id::create("m_monitor", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    if (get_is_active() == UVM_ACTIVE)
      m_driver.seq_item_port.connect(m_sequencer.seq_item_export);
    m_monitor.ap.connect(ap);
  endfunction
endclass
