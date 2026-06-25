// Auto-generated from scaffold-specification.json.
// Test: tpu_top_mac_smoke_test — Feature: F-01.
// Generated from scaffold-spec.json.
class tpu_top_tpu_top_mac_smoke_test_test extends tpu_top_base_test;
  `uvm_component_utils(tpu_top_tpu_top_mac_smoke_test_test)

  function new(string name = "tpu_top_tpu_top_mac_smoke_test_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "T-01";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    begin
      tpu_top_tpu_top_apb_weight_load_seq_seq seq = tpu_top_tpu_top_apb_weight_load_seq_seq::type_id::create("tpu_top_apb_weight_load_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_data_in_stream_seq_seq seq = tpu_top_tpu_top_data_in_stream_seq_seq::type_id::create("tpu_top_data_in_stream_seq");
      seq.start(m_env.m_data_in_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_start_seq_seq seq = tpu_top_tpu_top_start_seq_seq::type_id::create("tpu_top_start_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_apb_result_read_seq_seq seq = tpu_top_tpu_top_apb_result_read_seq_seq::type_id::create("tpu_top_apb_result_read_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    phase.drop_objection(this);
  endtask
endclass

// Test: tpu_top_full_compute_test — Feature: F-01.
// Generated from scaffold-spec.json.
class tpu_top_tpu_top_full_compute_test_test extends tpu_top_base_test;
  `uvm_component_utils(tpu_top_tpu_top_full_compute_test_test)

  function new(string name = "tpu_top_tpu_top_full_compute_test_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "T-02";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    begin
      tpu_top_tpu_top_apb_weight_load_seq_seq seq = tpu_top_tpu_top_apb_weight_load_seq_seq::type_id::create("tpu_top_apb_weight_load_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_data_in_stream_seq_seq seq = tpu_top_tpu_top_data_in_stream_seq_seq::type_id::create("tpu_top_data_in_stream_seq");
      seq.start(m_env.m_data_in_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_start_seq_seq seq = tpu_top_tpu_top_start_seq_seq::type_id::create("tpu_top_start_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_apb_result_read_seq_seq seq = tpu_top_tpu_top_apb_result_read_seq_seq::type_id::create("tpu_top_apb_result_read_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    phase.drop_objection(this);
  endtask
endclass

// Test: tpu_top_skew_align_test — Feature: F-02.
// Generated from scaffold-spec.json.
class tpu_top_tpu_top_skew_align_test_test extends tpu_top_base_test;
  `uvm_component_utils(tpu_top_tpu_top_skew_align_test_test)

  function new(string name = "tpu_top_tpu_top_skew_align_test_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "T-03";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    begin
      tpu_top_tpu_top_data_in_stream_seq_seq seq = tpu_top_tpu_top_data_in_stream_seq_seq::type_id::create("tpu_top_data_in_stream_seq");
      seq.start(m_env.m_data_in_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_start_seq_seq seq = tpu_top_tpu_top_start_seq_seq::type_id::create("tpu_top_start_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    phase.drop_objection(this);
  endtask
endclass

// Test: tpu_top_fifo_test — Feature: F-03.
// Generated from scaffold-spec.json.
class tpu_top_tpu_top_fifo_test_test extends tpu_top_base_test;
  `uvm_component_utils(tpu_top_tpu_top_fifo_test_test)

  function new(string name = "tpu_top_tpu_top_fifo_test_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "T-04";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    begin
      tpu_top_tpu_top_apb_weight_load_seq_seq seq = tpu_top_tpu_top_apb_weight_load_seq_seq::type_id::create("tpu_top_apb_weight_load_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_data_in_stream_seq_seq seq = tpu_top_tpu_top_data_in_stream_seq_seq::type_id::create("tpu_top_data_in_stream_seq");
      seq.start(m_env.m_data_in_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_fifo_boundary_seq_seq seq = tpu_top_tpu_top_fifo_boundary_seq_seq::type_id::create("tpu_top_fifo_boundary_seq");
      seq.start(m_env.m_data_in_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_start_seq_seq seq = tpu_top_tpu_top_start_seq_seq::type_id::create("tpu_top_start_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_apb_result_read_seq_seq seq = tpu_top_tpu_top_apb_result_read_seq_seq::type_id::create("tpu_top_apb_result_read_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    phase.drop_objection(this);
  endtask
endclass

// Test: tpu_top_apb_regfile_test — Feature: F-04.
// Generated from scaffold-spec.json.
class tpu_top_tpu_top_apb_regfile_test_test extends tpu_top_base_test;
  `uvm_component_utils(tpu_top_tpu_top_apb_regfile_test_test)

  function new(string name = "tpu_top_tpu_top_apb_regfile_test_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "T-05";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    begin
      tpu_top_tpu_top_apb_weight_load_seq_seq seq = tpu_top_tpu_top_apb_weight_load_seq_seq::type_id::create("tpu_top_apb_weight_load_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_apb_result_read_seq_seq seq = tpu_top_tpu_top_apb_result_read_seq_seq::type_id::create("tpu_top_apb_result_read_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    phase.drop_objection(this);
  endtask
endclass

// Test: tpu_top_counter_ctrl_test — Feature: F-05.
// Generated from scaffold-spec.json.
class tpu_top_tpu_top_counter_ctrl_test_test extends tpu_top_base_test;
  `uvm_component_utils(tpu_top_tpu_top_counter_ctrl_test_test)

  function new(string name = "tpu_top_tpu_top_counter_ctrl_test_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "T-06";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    begin
      tpu_top_tpu_top_apb_weight_load_seq_seq seq = tpu_top_tpu_top_apb_weight_load_seq_seq::type_id::create("tpu_top_apb_weight_load_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_data_in_stream_seq_seq seq = tpu_top_tpu_top_data_in_stream_seq_seq::type_id::create("tpu_top_data_in_stream_seq");
      seq.start(m_env.m_data_in_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_start_seq_seq seq = tpu_top_tpu_top_start_seq_seq::type_id::create("tpu_top_start_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_apb_result_read_seq_seq seq = tpu_top_tpu_top_apb_result_read_seq_seq::type_id::create("tpu_top_apb_result_read_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    phase.drop_objection(this);
  endtask
endclass

// Test: tpu_top_rerun_test — Feature: F-05.
// Generated from scaffold-spec.json.
class tpu_top_tpu_top_rerun_test_test extends tpu_top_base_test;
  `uvm_component_utils(tpu_top_tpu_top_rerun_test_test)

  function new(string name = "tpu_top_tpu_top_rerun_test_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "T-07";
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    begin
      tpu_top_tpu_top_apb_weight_load_seq_seq seq = tpu_top_tpu_top_apb_weight_load_seq_seq::type_id::create("tpu_top_apb_weight_load_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_data_in_stream_seq_seq seq = tpu_top_tpu_top_data_in_stream_seq_seq::type_id::create("tpu_top_data_in_stream_seq");
      seq.start(m_env.m_data_in_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_start_seq_seq seq = tpu_top_tpu_top_start_seq_seq::type_id::create("tpu_top_start_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_rerun_seq_seq seq = tpu_top_tpu_top_rerun_seq_seq::type_id::create("tpu_top_rerun_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    begin
      tpu_top_tpu_top_apb_result_read_seq_seq seq = tpu_top_tpu_top_apb_result_read_seq_seq::type_id::create("tpu_top_apb_result_read_seq");
      seq.start(m_env.m_core_agent.m_sequencer);
    end
    phase.drop_objection(this);
  endtask
endclass
