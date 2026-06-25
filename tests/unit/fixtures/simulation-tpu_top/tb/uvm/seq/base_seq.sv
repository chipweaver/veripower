class tpu_top_base_seq extends uvm_sequence #(uvm_sequence_item);
  `uvm_object_utils(tpu_top_base_seq)

  function new(string name = "tpu_top_base_seq");
    super.new(name);
  endfunction

  task body();
    `uvm_info(get_type_name(), "NOTE: base body is a no-op; override in a concrete sequence to drive stimulus.", UVM_LOW)
  endtask
endclass
