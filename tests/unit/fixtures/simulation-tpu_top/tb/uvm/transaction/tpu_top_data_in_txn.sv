// Transaction for data_in agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class tpu_top_data_in_txn extends uvm_sequence_item;
  `uvm_object_utils_begin(tpu_top_data_in_txn)
    `uvm_field_int(in1, UVM_ALL_ON)
    `uvm_field_int(in2, UVM_ALL_ON)
    `uvm_field_int(in1_en, UVM_ALL_ON)
    `uvm_field_int(in2_en, UVM_ALL_ON)
    `uvm_field_int(cyc, UVM_ALL_ON | UVM_NOCOMPARE)
  `uvm_object_utils_end

  rand logic [31:0] in1;
  rand logic [31:0] in2;
  rand logic        in1_en;
  rand logic        in2_en;
  // Absolute cycle stamp (set by the monitor; not driven onto the DUT).
  longint unsigned  cyc;

  // Input enables default low unless a sequence drives a push this cycle.
  constraint c_default_idle {
    soft in1_en == 1'b0;
    soft in2_en == 1'b0;
  }

  function new(string name = "tpu_top_data_in_txn");
    super.new(name);
  endfunction

  virtual function string convert2string();
    return $sformatf("data_in_txn cyc=%0d in1=0x%08h in2=0x%08h in1_en=%0b in2_en=%0b",
                     cyc, in1, in2, in1_en, in2_en);
  endfunction
endclass
