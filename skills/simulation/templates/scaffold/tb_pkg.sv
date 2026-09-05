// The TB package for {{MODULE}}.
// GENERATED every round from the plan — the include list is the plan's agent, sequence and
// checker names, so an include you add here is gone next round, and the file it named is
// left behind uncompiled. A check the env must instantiate goes into the reference model or
// the scoreboard named below; one that stands on its own goes in a file listed in
// tb/uvm/tb_sources.f, which is not regenerated.
package {{MODULE}}_tb_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // === Shared base (do not modify) ===
  `include "base_seq.sv"

  // === Transactions ===
{{TXN_INCLUDES}}

  // === Agent infrastructure ===
{{AGENT_INCLUDES}}

  // === Reference model & checker ===
  `include "{{RM_NAME}}.sv"
  `include "{{SB_NAME}}.sv"

  // === Environment ===
  `include "{{MODULE}}_env.sv"

  // === Base test (after env: base_test instantiates {{MODULE}}_env) ===
  `include "base_test.sv"

  // === Sequences ===
{{SEQ_INCLUDES}}

  // === Tests ===
  `include "generated_tests.svh"
endpackage
