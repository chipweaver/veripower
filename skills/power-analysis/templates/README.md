# Verification/power-analysis/ — bootstrap-deployed workspace

`power-analysis` stage workdir, holding both segments of the flow: GLS power simulation + PT-PX averaged power analysis.

## Entry commands

| Command | Description |
|---|---|
| `make tb-shim` | Generates `tb_filelist_abs.f` from `simulation/filelist.f` (absolute-path rewrite, drops `-f rtl_filelist.f`; auto-prerequisite of `gls-compile`). |
| `make refresh-tests` | Re-renders the power test classes + `power_filelist.f` against the current `power_scenarios[]` (auto-prerequisite of `gls-compile`; plan changes are auto-re-rendered here without a re-bootstrap). |
| `make gls-compile` | Builds `simv` (first `tb-shim` + `refresh-tests`, then SDF back-annotation + UVM + power tests). |
| `make gls-run` | Iterates `power_scenarios[]` to run `simv` and produce `saif/<id>.saif`. |
| `make ptpx` | Iterates `saif/<id>.saif` to run PT-PX averaged and produce `reports_ptpx/<id>/*`. |
| `make all` | Runs the three above in series (default target). |
| `make clean` | Cleans build outputs (keeps `env.sh` / `Makefile` / `scripts/` / `scaffold/*.tmpl`). |

## Required env

```bash
export LIB_V=/path/to/stdcell.v          # standard cell behavioral models (Verilog)
export LIB_DB=/path/to/stdcell.db        # standard cell Liberty .db (same as synthesis stage)
export UVM_HOME=/path/to/uvm-1.1d        # UVM source tree (provides src/dpi/uvm_dpi.cc)
```

When unset, sourcing `env.sh` errors out (`:?` pattern).

## External reference inputs

The power bootstrap verb deploys templates and the initial power tests in one shot, computes a relative path based on workdir depth, and then substitutes the `MY_SYN_OUT` / `MY_SIM_DIR` / `MY_PLAN_DIR` placeholders inside `env.sh` — these three relative paths are bound to the environment variables that `env.sh` exports, every Makefile target references files via those environment variables, and the workspace can be moved (e.g., to `runs/<N>/`) without any hand-edited path. Plan / scenario changes are auto-re-rendered by `make refresh-tests` (already wired as a `gls-compile` prerequisite); no re-bootstrap is needed.

- `${NETLIST}` / `${SDC_FILE}` / `${SDF_FILE}` — the synthesis trio (`<TOP>_syn.{v,sdc,sdf}`).
- `${TB_FILELIST}` — UVM TB infrastructure raw filelist; `make tb-shim` rewrites it into `${TB_FILELIST_ABS}` (absolute-pathized) for VCS to consume across workdirs.
- `${PLAN_DIR}` — the simulation-plan workdir (`sequences.json` / `power-scenarios.json`).

For the expanded path shapes, see the deployed `env.sh`.

## Outputs

- `saif/<id>.saif` — per-scenario gate-level SAIF (hardlinked to `_dedup/<seq>.saif`).
- `tb_filelist_abs.f` — absolute-pathized simulation filelist produced by `make tb-shim` (`make clean` removes it; the `scripts/build_tb_filelist_abs.py` template is kept).
- `reports_ptpx/<id>/{power_hier.rpt, power_flat.rpt, switching_activity.rpt, ptpx.log}` — per-SAIF PT-PX reports.
- `result.json` — stage envelope (`saif_artifacts[]` / `ppa_actual[]` / `power_by_scenario[]` / `failures[]` / `violations[]`).

For field semantics, see `${CLAUDE_SKILL_DIR}/references/result.schema.json`.
