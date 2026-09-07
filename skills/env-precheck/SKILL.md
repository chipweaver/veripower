---
name: env-precheck
description: Use when checking whether this machine's Python, EDA tools and licenses can actually run VeriPower's stages; not for any pipeline stage, module state, or design work.
---

# Environment Pre-check

Pre-pipeline, own session: you report, and change nothing — no module file, no event, no
`kernel.py`. Nothing in the pipeline depends on this having run.

`<skill>` is this skill's own base directory, named on the first line of this file.

## 1. Presence

`<skill>/../../docs/eda-env.md` lists what must be true and what each miss costs. Probe every row
of it, and `timeout` every probe: an unreachable license server hangs the tool.

## 2. Smoke

Presence is not a checkout. Ask which stages to cover, then per row write the smallest input that
forces the checkout and run it in a temp dir. A row passes iff it produces the file below — a
tool that took the license and did nothing still exits 0.

| Checkout | Hinges on | Produces | Gates |
|---|---|---|---|
| Design Compiler | `compile_ultra` (the DC-Ultra checkout — the flow runs no plain `compile`), then `write` | the netlist | synthesis |
| PrimeTime | `report_timing` on that netlist | the timing report | timing-analysis |
| PrimeTime-PX | `set power_enable_analysis TRUE` + `report_power` | the power report | power-analysis |
| VCS + UVM | compiling `uvm_pkg.sv` and `uvm_dpi.cc` from `UVM_HOME`, then running simv | whatever the TB writes | simulation, power-analysis |
| VCS coverage | `-cm line+cond+branch+tgl+fsm`, then `urg -report cov_merge -format text` | `cov_merge/dashboard.txt` | simulation coverage gate |
| Verdi / FSDB | `-debug_access+all -kdb -lca` + a ucli `$fsdbDumpvars`, then `fsdbreport` | the fsdbreport output | simulation waveform, simulation-triage |
| SpyGlass Lint | `current_goal lint/lint_rtl` + `run_goal` | that goal's `moresimple.rpt` | lint-cdc |
| SpyGlass CDC | `cdc/cdc_setup`, `cdc/cdc_setup_check`, `cdc/cdc_verify_struct`, each `run_goal` | each goal's `moresimple.rpt` | lint-cdc |

The three VCS rows each compile their own simv: coverage and FSDB instrumentation take effect at
compile time. A row whose tool or variable already failed §1 is skipped, not failed.

## 3. Report

Per row: pass or fail, and the stages it costs. Close with the stage list runnable now.

- `lmstat` explains, the smoke decides: a feature the server lists can still fail to check out,
  and lmstat missing or timing out is not a failure.
- Print `export` lines for the user; never edit their shell config.
