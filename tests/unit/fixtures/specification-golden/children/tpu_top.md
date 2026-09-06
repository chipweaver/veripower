---
child: tpu_top
parent: tpu_top
ports:
  - "mem[0]"
  - "mem[1]"
  - "mem[2]"
  - "mem[3]"
  - out1
  - out2
  - result_fifo_i_data
  - result_fifo_o_data
  - fifo_en
  - i_clk
  - i_rstn
  - in1
  - in2
  - in1_en
  - in2_en
  - start
  - o_full
  - o_empty
  - done
  - i_paddr
  - i_psel
  - i_pwrite
  - i_pwdata
  - i_penable
  - o_prdata
  - counter
clocks:
  - { name: i_clk, domain: i_clk }
---

Stub: check-crossrefs reads the frontmatter above; nothing reads a body.
