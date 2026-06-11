package {{MODULE}}_tb_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // === Shared base (do not modify) ===
  `include "base_seq.sv"
  `include "base_test.sv"

  // === Transactions ===
{{TXN_INCLUDES}}

  // === Agent infrastructure ===
{{AGENT_INCLUDES}}

  // === Reference model & checker ===
  `include "{{RM_NAME}}.sv"
  `include "{{SB_NAME}}.sv"

  // === Environment ===
  `include "{{MODULE}}_env.sv"

  // === Sequences ===
{{SEQ_INCLUDES}}

  // === Tests ===
  `include "generated_tests.svh"
endpackage
