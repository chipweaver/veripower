package tpu_top_tb_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // === Shared base (do not modify) ===
  `include "base_seq.sv"

  // === Transactions ===
  `include "tpu_top_data_in_txn.sv"
  `include "tpu_top_core_txn.sv"

  // === Agent infrastructure ===
  `include "tpu_top_data_in_driver.sv"
  `include "tpu_top_data_in_monitor.sv"
  `include "tpu_top_data_in_agent.sv"
  `include "tpu_top_core_driver.sv"
  `include "tpu_top_core_monitor.sv"
  `include "tpu_top_core_agent.sv"

  // === Reference model & checker ===
  `include "tpu_top_tpu_top_rm.sv"
  `include "tpu_top_tpu_top_scoreboard.sv"

  // === Environment ===
  `include "tpu_top_env.sv"

  // === Base test (after env: base_test instantiates tpu_top_env) ===
  `include "base_test.sv"

  // === Sequences ===
  `include "tpu_top_tpu_top_apb_weight_load_seq_seq.sv"
  `include "tpu_top_tpu_top_data_in_stream_seq_seq.sv"
  `include "tpu_top_tpu_top_start_seq_seq.sv"
  `include "tpu_top_tpu_top_apb_result_read_seq_seq.sv"
  `include "tpu_top_tpu_top_fifo_boundary_seq_seq.sv"
  `include "tpu_top_tpu_top_rerun_seq_seq.sv"
  `include "tpu_top_tpu_top_idle_seq_seq.sv"
  `include "tpu_top_tpu_top_traffic_seq_seq.sv"
  `include "tpu_top_tpu_top_peak_toggle_seq_seq.sv"

  // === Tests ===
  `include "generated_tests.svh"
endpackage
