# synthesis run directory

Design Compiler synthesis for one module, deployed here by the `veripower:synthesis` stage's
bootstrap verb. The stage SOP lives in `${CLAUDE_SKILL_DIR}/SKILL.md`.

`make help` lists the targets. `make synthesis` runs `dc_shell` and tees `run.log`; the netlist
and post-synthesis constraints land in `out/`, the reports in `reports/`.

## The two files you edit

| File | Content |
|---|---|
| `constraints.sdc` | The timing constraints DC reads: the specification SDC verbatim on a first run. Your `create_generated_clock` / `set_multicycle_path` / `set_false_path` exceptions and the `set_clock_uncertainty` / `set_drive` / `set_load` values go here; flag any placeholder value you leave behind with a `# notes:` comment. |
| `scripts/config.tcl` | `TOP` and `LIB_DB` for `dc_shell`, which inherits no shell environment variables. Replace the `FILL_IN_LIB_DB_PATH` placeholder (or export `LIB_DB` before the first `make synthesis`); editing it here needs no re-bootstrap. |

Everything else here is generated or make-internal. `scripts/rtl_load.tcl` is regenerated from
the rtl-design file layout on every deploy, so edits to it do not survive. Each file carries a
header comment describing its own format.
