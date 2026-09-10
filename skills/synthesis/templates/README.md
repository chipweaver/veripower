# synthesis run directory

Design Compiler synthesis for one module, deployed here by the `veripower:synthesis` stage's
bootstrap verb. That skill's own `SKILL.md` is the stage SOP.

`make help` lists the targets. `make synthesis` runs `dc_shell` and tees `run.log`; the netlist
and post-synthesis constraints land in `out/`, the reports in `reports/`.

`LIB_DB` and `WIRE_LOAD_MODEL` must both be in the environment before `make`: the standard-cell
Liberty `.db`, and either a wire load model the library carries (`report_lib` lists them) or
`none`. `env.sh` refuses to run without either, so the `FILL_IN_` placeholders in
`scripts/config.tcl` are a fallback for a `dc_shell` started outside the Makefile, not a second
way to set them.

## The one file you edit

`constraints.local.sdc` holds this stage's constraints and is carried into the next round.
DC reads the specification seed in `constraints.sdc`, then this local file on every run.
Your `create_generated_clock` / `set_multicycle_path` / `set_false_path` exceptions
and the `set_clock_uncertainty` / `set_drive` / `set_load` values go here; flag any placeholder
value you leave behind with a `# notes:` comment.

Everything else here is generated or make-internal. `scripts/rtl_load.tcl` is regenerated from
the rtl-design file layout on every deploy, so edits to it do not survive. Each file carries a
header comment describing its own format.
