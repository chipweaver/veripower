---
child: systolic_reg
parent: tpu_top
ports:
  - systolic_in1
  - systolic_in2
  - mac00_in
  - mac10_in
  - i_clk
  - i_rstn
clocks:
  - { name: i_clk, domain: i_clk }
---

Stub: check-crossrefs reads the frontmatter above; nothing reads a body.
