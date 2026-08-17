# power-analysis run directory

Gate-level power simulation and PrimeTime PX averaged power analysis for one module, deployed
here by the `veripower:power-analysis` stage's bootstrap verb. That skill's own `SKILL.md` is the
stage SOP.

`make help` lists the targets. `make all` is the whole flow: it builds `simv` against the
synthesis netlist and the simulation testbench, runs one simulation per power scenario into
`saif/`, and runs PT-PX over each SAIF into `reports_ptpx/<id>/`.

`LIB_V`, `LIB_DB` and `UVM_HOME` must be in the environment before `make`. `env.sh` refuses to
run unless all three name a readable file, and every target sources it, so a wrong path stops
the first target rather than the last.

## No file here is yours to edit

Everything is deployed from templates or generated. The UVM power test classes under
`scaffold/power_tests/` are re-rendered from the current plan before every compile, so edits to
them do not survive. Each file carries a header comment describing its own format.
