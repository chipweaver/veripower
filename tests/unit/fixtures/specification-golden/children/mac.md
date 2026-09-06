---
child: mac
parent: tpu_top
ports:
  - i_clk
  - i_rstn
  - mac00_in
  - mac00_out
  - mac01_in
  - mac01_out
  - mac10_in
  - mac11_in
  - "mem[0]"
  - "mem[1]"
  - "mem[2]"
  - "mem[3]"
  - "32'h0"
  - out1
  - out2
clocks:
  - { name: i_clk, domain: i_clk }
---

Stub: check-crossrefs reads the frontmatter above; nothing reads a body.
