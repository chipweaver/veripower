// Environment for tpu_top.
// Generated from scaffold-spec.json. Typically nothing to fill — fully assembled.
class tpu_top_env extends uvm_env;
  `uvm_component_utils(tpu_top_env)

  tpu_top_data_in_agent m_data_in_agent;
  tpu_top_core_agent m_core_agent;
  tpu_top_tpu_top_rm  m_rm;
  tpu_top_tpu_top_scoreboard m_scoreboard;

  function new(string name = "tpu_top_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    m_data_in_agent = tpu_top_data_in_agent::type_id::create("m_data_in_agent", this);
    m_data_in_agent.is_active = UVM_ACTIVE;
    m_core_agent = tpu_top_core_agent::type_id::create("m_core_agent", this);
    m_core_agent.is_active = UVM_ACTIVE;
    m_rm = tpu_top_tpu_top_rm::type_id::create("m_rm", this);
    m_scoreboard = tpu_top_tpu_top_scoreboard::type_id::create("m_scoreboard", this);
  endfunction

  function void connect_phase(uvm_phase phase);
    m_data_in_agent.ap.connect(m_rm.ai_data_in);
    m_core_agent.ap.connect(m_scoreboard.analysis_export);
    m_core_agent.ap.connect(m_rm.ai_core);
    // Hand the scoreboard a handle to the single env RM so check_phase can poll
    // the per-cycle predictions (the RM receives both input streams; the
    // scoreboard subscribes only to the core observer txn).
    m_scoreboard.rm = m_rm;
  endfunction
endclass
