# lint-cdc run directory

SpyGlass lint + CDC for one module, deployed here by the `veripower:lint-cdc` stage's
bootstrap verb. That skill's own `SKILL.md` is the stage SOP.

`make help` lists the targets. `make all` runs lint and CDC in a single session and is the
recommended first run; `make lint` and `make cdc` run one goal each.

## The two files you edit

| File | Content |
|---|---|
| `scripts/local.sgdc` | This stage's port/clock associations and analysis scope, carried into the next round. SpyGlass reads it after the generated seed and annotations in `scripts/constraints.sgdc` on every run. |
| `scripts/waiver.tcl` | Reviewed waivers, and any `set_option` the analysis needs. `run.tcl` sources it for both goals. |

Everything else here is generated or make-internal. `scripts/filelist.txt` is regenerated from
the rtl-design file layout on every deploy, so edits to it do not survive. Each file carries a
header comment describing its own format.
