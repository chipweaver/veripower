# lint-cdc run directory

SpyGlass lint + CDC for one module, deployed here by the `veripower:lint-cdc` stage's
bootstrap verb. That skill's own `SKILL.md` is the stage SOP.

`make help` lists the targets. `make all` runs lint and CDC in a single session and is the
recommended first run; `make lint` and `make cdc` run one goal each.

## The two files you edit

| File | Content |
|---|---|
| `scripts/constraints.sgdc` | Clock / reset / port constraints and the depth annotations (`sync_cell`, `reset_synchronizer`, `set_case_analysis`, `quasi_static`) that suppress false positives. Seeded from the specification stage on a first run, carried forward from the previous round after that. |
| `scripts/waiver.tcl` | Reviewed waivers, and any `set_option` the analysis needs. `run.tcl` sources it for both goals. |

Everything else here is generated or make-internal. `scripts/filelist.txt` is regenerated from
the rtl-design file layout on every deploy, so edits to it do not survive. Each file carries a
header comment describing its own format.
