class MY_MODULE_base_test extends uvm_test;
  `uvm_component_utils(MY_MODULE_base_test)

  MY_MODULE_env m_env;
  string m_test_id;

  function new(string name = "MY_MODULE_base_test", uvm_component parent = null);
    super.new(name, parent);
    m_test_id = "unassigned";
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    m_env = MY_MODULE_env::type_id::create("m_env", this);
  endfunction

  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    `uvm_info(get_type_name(), $sformatf("Running derived test_id=%0s", m_test_id), UVM_LOW)
    #1ns;
    phase.drop_objection(this);
  endtask

endclass
