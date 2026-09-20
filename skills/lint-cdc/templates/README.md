# lint-cdc run directory

SpyGlass lint + CDC for one module, deployed here by the `veripower:lint-cdc` stage's
bootstrap verb. That skill's own `SKILL.md` is the stage SOP.

`make help` lists the targets. `make all` runs lint and CDC in a single session and is the
recommended first run. `make lint` runs `lint_rtl`; `make cdc` runs `cdc_setup`,
`cdc_setup_check` and `cdc_verify_struct`.

## Setup

Bootstrap regenerates `scripts/filelist.txt` from the RTL file layout and
`scripts/constraints.sgdc` from the specification seed and RTL annotations. Correct these
inputs at their sources. It installs missing setup and preserves existing files, including
`env.sh`, `scripts/spyglass_lint.prj` and `scripts/run.tcl`.

| File | Content |
|---|---|
| `scripts/local.sgdc` | This stage's port/clock associations and analysis scope, carried into the next round. SpyGlass reads it after the generated seed and annotations in `scripts/constraints.sgdc` on every run. |
| `scripts/waiver.tcl` | Reviewed waivers and analysis options, sourced before the goals run. |
