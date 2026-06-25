// Transaction for core agent.
// Generated from scaffold-spec.json. Fill domain-labeled stubs per verification-plan.md test strategy.
class tpu_top_core_txn extends uvm_sequence_item;
  `uvm_object_utils_begin(tpu_top_core_txn)
    // Driven inputs (apb access + ctrl start).
    `uvm_field_int(i_paddr, UVM_ALL_ON)
    `uvm_field_int(i_psel, UVM_ALL_ON)
    `uvm_field_int(i_pwrite, UVM_ALL_ON)
    `uvm_field_int(i_pwdata, UVM_ALL_ON)
    `uvm_field_int(i_penable, UVM_ALL_ON)
    `uvm_field_int(start, UVM_ALL_ON)
    // DUT outputs sampled by the monitor — never randomized/driven, so they are
    // NOCOMPARE for UVM's built-in field compare (the scoreboard compares each
    // of them against the RM prediction explicitly with 4-state ===).
    `uvm_field_int(o_prdata, UVM_ALL_ON | UVM_NOCOMPARE)
    `uvm_field_int(counter,  UVM_ALL_ON | UVM_NOCOMPARE)
    `uvm_field_int(o_full,   UVM_ALL_ON | UVM_NOCOMPARE)
    `uvm_field_int(o_empty,  UVM_ALL_ON | UVM_NOCOMPARE)
    `uvm_field_int(done,     UVM_ALL_ON | UVM_NOCOMPARE)
    `uvm_field_int(cyc,      UVM_ALL_ON | UVM_NOCOMPARE)
  `uvm_object_utils_end

  // Driven inputs.
  rand logic [31:0] i_paddr;
  rand logic        i_psel;
  rand logic        i_pwrite;
  rand logic [31:0] i_pwdata;
  rand logic        i_penable;
  rand logic        start;
  // DUT outputs sampled by the monitor; never randomized/driven.
  logic [31:0]      o_prdata;
  logic [3:0]       counter;
  logic [2:0]       o_full;
  logic [2:0]       o_empty;
  logic             done;
  // Absolute cycle stamp (set by the monitor; not driven onto the DUT).
  longint unsigned  cyc;

  // APB strobes + start default idle unless a sequence drives an access this
  // cycle. i_paddr restricted to the 4 weight-file addresses.
  constraint c_default_idle {
    soft i_psel    == 1'b0;
    soft i_penable == 1'b0;
    soft i_pwrite  == 1'b0;
    soft start     == 1'b0;
    soft i_paddr  inside {[0:3]};
  }

  function new(string name = "tpu_top_core_txn");
    super.new(name);
  endfunction

  virtual function string convert2string();
    return $sformatf({"core_txn cyc=%0d paddr=%0d psel=%0b pwrite=%0b penable=%0b ",
                      "pwdata=0x%08h start=%0b | o_prdata=0x%08h counter=%0d ",
                      "o_full=0x%01h o_empty=0x%01h done=%0b"},
                     cyc, i_paddr, i_psel, i_pwrite, i_penable, i_pwdata, start,
                     o_prdata, counter, o_full, o_empty, done);
  endfunction
endclass
