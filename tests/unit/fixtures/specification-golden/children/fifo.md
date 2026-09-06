---
child: fifo
parent: tpu_top
ports:
  - fifo_en
  - result_fifo_i_data
  - result_fifo_o_data
  - systolic_in1
  - systolic_in2
  - in1
  - in2
  - in1_en
  - in2_en
  - o_full
  - o_empty
  - i_clk
  - i_rstn
clocks:
  - { name: i_clk, domain: i_clk }
---

Stub: check-crossrefs reads the frontmatter above; nothing reads a body.
