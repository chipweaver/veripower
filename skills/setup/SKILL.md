---
name: setup
description: Use when checking whether this machine's Python, EDA tools and licenses can actually run VeriPower's stages; not for any pipeline stage, module state, or design work.
---

# Environment Setup Check

Pre-pipeline, own session. Write no module file, append no event, call no `kernel.py` verb.
Report only; nothing in the pipeline depends on this having run.

## 1. Presence

`${CLAUDE_SKILL_DIR}/../../docs/eda-env.md` is the requirement source — read it and run each
row's sanity check rather than restating it here. Two exceptions: its check for `LIB_DB` /
`LIB_V` / `UVM_HOME` is a stage `env.sh` guard that presupposes a deployed work tree, so here
test that each is set and its path readable; and `make` / `urg` have no row there at all.
`timeout` every probe — an unreachable license server hangs the tool.

What a missing row costs:

| Missing | Stages lost |
|---|---|
| `python3`, `jsonschema` >= 4.18, `referencing`, `PyYAML` | all |
| `/bin/sh` → bash, `make` | every EDA stage |
| `vcs`, `urg`, `fsdbreport`, `fsdb2vcd`, `UVM_HOME` | simulation, power-analysis, simulation-triage |
| `dc_shell`, `LIB_DB` | synthesis, timing-analysis, power-analysis |
| `pt_shell` | timing-analysis, power-analysis |
| `LIB_V` | power-analysis |
| `spyglass` | lint-cdc |

`specification`, `simulation-plan` and `rtl-design` need only the first row.

## 2. Smoke

Presence is not a checkout. Ask which stages to cover — cover every row when there is nobody to
ask — then run one minimal job per row in a temp dir: write the DUT (one clocked flop), the TB
(`import uvm_pkg::*`) and each tcl yourself, mirroring how that stage invokes the tool in
`${CLAUDE_SKILL_DIR}/../<stage>/templates/`. A row passes iff it produces the file below.

| Checkout | Hinges on | Produces | Gates |
|---|---|---|---|
| Design Compiler | `compile`, then `write` | the netlist | synthesis |
| PrimeTime | `report_timing` on that netlist | the timing report | timing-analysis |
| PrimeTime-PX | `set power_enable_analysis TRUE` + `report_power` | the power report | power-analysis |
| VCS + UVM | compiling `uvm_pkg.sv` and `uvm_dpi.cc` from `UVM_HOME`, then running simv | whatever the TB writes | simulation, power-analysis |
| VCS coverage | `-cm line+cond+branch+tgl+fsm`, then `urg -report cov_merge -format text` | `cov_merge/dashboard.txt` | simulation coverage gate |
| Verdi / FSDB | `-debug_access+all -kdb -lca` + a ucli `$fsdbDumpvars`, then `fsdbreport` (argv form in simulation-triage's SKILL.md) | the fsdbreport output | simulation waveform, simulation-triage |
| SpyGlass Lint | `current_goal lint/lint_rtl` + `run_goal` | that goal's `moresimple.rpt` | lint-cdc |
| SpyGlass CDC | `cdc/cdc_setup`, `cdc/cdc_setup_check`, `cdc/cdc_verify_struct`, each `run_goal` | each goal's `moresimple.rpt` | lint-cdc |

Run rows 1 and 4 first: 2–3 read row 1's netlist, 5–6 reuse row 4's simv. Rows 1–3 need `LIB_DB`
and 4–6 need `UVM_HOME`; a row whose tool or variable already failed §1 is skipped, not failed —
§1 has said it, and a second verdict on it would only be a worse-sourced copy. The
SDC and the SGDC belong to specification and to `bootstrap`, so write a bare `create_clock` and
a two-line SGDC yourself.

## 3. Report

Per row: pass or fail, and the stages it costs. Close with the stage list runnable now.

- `lmstat` explains, the smoke decides — a feature the server lists can still fail to check out,
  and lmstat missing or timing out is not a failure.
- DC-Ultra is advisory: the flow runs `compile`, not `compile_ultra`. Try `compile_ultra` on a
  fresh elaborate and report it; never gate on it.
- An `urg -version` other than L-2016.06 is a warning — the coverage parser is layout-sensitive.
- Print `export` lines for the user; never edit their shell config.
