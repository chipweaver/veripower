# EDA Tool Environment

Templates and scripts invoke the installed EDA tools as the calling user, in a single execution environment: stage
scripts and the tools they launch see the same filesystem, tool processes
inherit the caller's exported variables, and a tool-produced executable (a VCS
`simv`) runs from the same shell that built it. Produced artifacts inherit
caller ownership. The requirements below define the execution environment; select tool releases,
standard-cell libraries and compilers that support the stages you run.

## Mandatory

The table lists the requirements and the stages that use them. The `env-precheck`
skill checks tool and environment availability, then runs license and execution
smoke checks for the stages selected by the user.

| Required | Purpose | Used by |
|---|---|---|
| `python3` >= 3.10 with `jsonschema` >= 4.18, `referencing`, `PyYAML` | Python runtime and schema validation used by the engine and stage scripts | all |
| `LM_LICENSE_FILE` and/or `SNPSLMD_LICENSE_FILE` | License server configuration read by the Synopsys tools at launch. `env-precheck` exercises checkouts for the selected stages | every EDA stage |
| `make` | The stages that ship a Makefile drive their tool through it | lint-cdc, simulation |
| `/bin/sh` → `bash` **where VCS runs** | The VCS launcher is `#!/bin/sh -h` and relies on bash semantics. That is the machine the launcher executes on, which is not always the one you type on: with a containerized install the host's `/bin/sh` can be `dash` and every other stage still runs | simulation, power-analysis |
| `vcs`, `UVM_HOME` | Compiling and running the UVM testbench, and the gate-level run that produces the SAIF | simulation, power-analysis |
| `urg` | Merging and reporting structural coverage, which the coverage gate parses | simulation's coverage gate |
| `fsdbreport`, `fsdb2vcd` | Querying the FSDB simulation dumps (`vcs -debug_access+all -kdb -lca` plus a `-ucli` do-file `$fsdbDumpvars`) | simulation-triage |
| `dc_shell`, and a **DC-Ultra** entitlement on the license server | Mapping with `compile_ultra` in `dc_run.tcl`; timing and area measurements come from `timing_setup.rpt` and `area.rpt`, with `qor.rpt` used to cross-check setup violations | synthesis |
| `pt_shell` | Timing and power analysis of the mapped netlist | timing-analysis, power-analysis |
| `LIB_DB` | The std-cell Liberty `.db` that mapping links against and that both analyses re-link | synthesis, timing-analysis, power-analysis |
| `LIB_V` | The std-cell Verilog models the gate-level run needs | power-analysis |
| `WIRE_LOAD_MODEL` | synthesis's interconnect estimate: a model the library carries, or `none`. Select explicitly for the intended interconnect estimate; it affects timing and area | synthesis |
| `spyglass` | Lint and CDC goals | lint-cdc |

`specification`, `simulation-plan` and `rtl-design` need only the first row. Timing-analysis and power-analysis also depend on the netlist synthesis writes.

## Optional

| Variable | When to set | How |
|---|---|---|
| `VCS_CC` / `VCS_CPP` | Pin the C/C++ compiler when the host's default GCC produces objects incompatible with VCS's prebuilt non-PIC objects (typical symptom: link-time errors building `simv`). VeriPower passes them through conditionally via `${VCS_CC:+-cc "$VCS_CC"}` | `export VCS_CC=<gcc>` and `export VCS_CPP=<g++>` (e.g., `gcc-4.8`/`g++-4.8` is a known-good pairing for some VCS-on-modern-distro combinations) |

## Coverage report (urg text layout)

`simulation`'s structural-coverage gate parses the **text** report from `urg` (`dashboard.txt` +
`modinfo.txt`) into `structural-coverage.json` (`parse_coverage.py`). Two things it needs:

- **`-format text`.** The parser reads urg's text tables.
- **`-report <dir>` and `--cov-dir` naming the same directory.** `-report` names where urg writes,
  not what it reports — the `coverage` target passes both on one line, so they agree by
  construction.

Which dim columns appear is not fixed. urg prints the columns it has, which follows the `-cm`
metrics compiled in (`VCS_COV`) and what the `.vdb` holds: a real run without branch coverage
prints five columns, and runs with covergroups print a `GROUP` column beside the structural ones.
The parser reads each instance subtree table in `modinfo.txt` by its column header. A missing
or N/A measurement cannot satisfy a numeric bound. The gate uses the full DUT instance path,
including its children, and excludes the TB and peer instances.

## Convention

Keep all of the above in a site-level EDA env file sourced from your `~/.bashrc`.

## Troubleshooting

- **`/bin/sh` resolves to something other than `bash`** (e.g., `dash` on some Debian-family defaults): repoint with the distro's standard mechanism — on Debian/Ubuntu that is `sudo dpkg-reconfigure dash` answered "No".
- **A variable is missing or a configured path cannot be found:** check the exported value and whether it is visible to the tool process. Load the site's EDA environment file or correct the setting before searching for a replacement. Stage `env.sh` comments describe the expected paths.
