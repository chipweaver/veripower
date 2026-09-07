# EDA Tool Environment

VeriPower does not pin EDA install paths in the plugin. Templates and scripts
invoke tools as the calling user, in a single execution environment: stage
scripts and the tools they launch see the same filesystem, tool processes
inherit the caller's exported variables, and a tool-produced executable (a VCS
`simv`) runs from the same shell that built it. Produced artifacts inherit
caller ownership. VeriPower is not tied to specific EDA tool releases or Linux
distributions — the "mandatory" set below is what VeriPower contracts on;
everything else (which VCS release, which std-cell library, which compiler) is
a deployment choice.

## Mandatory

What must be true, and which stages you lose without it. The `env-precheck` skill probes every row
below against a live machine and smoke-runs each license checkout.

| Required | Purpose | Stages lost |
|---|---|---|
| `python3` >= 3.10 with `jsonschema` >= 4.18, `referencing`, `PyYAML` | The kernel and every stage gate validate result/review schemas (`registry=`-based `$ref` resolution needs the post-4.18 jsonschema API); the stage CLIs annotate `list[str] \| None` in evaluated signature position, which is a TypeError before 3.10 | all |
| `LM_LICENSE_FILE` and/or `SNPSLMD_LICENSE_FILE` | Synopsys license server checkout — every tool reads these at launch, and VeriPower does not validate them | every EDA stage |
| `make` | The stages that ship a Makefile drive their tool through it | lint-cdc, simulation, synthesis, power-analysis |
| `/bin/sh` → `bash` **where VCS runs** | The VCS launcher is `#!/bin/sh -h` and relies on bash semantics. That is the machine the launcher executes on, which is not always the one you type on: with a containerized install the host's `/bin/sh` can be `dash` and every other stage still runs | simulation, power-analysis |
| `vcs`, `UVM_HOME` | Compiling and running the UVM testbench, and the gate-level run that produces the SAIF | simulation, power-analysis |
| `urg` | Merging and reporting structural coverage, which the coverage gate parses | simulation's coverage gate |
| `fsdbreport`, `fsdb2vcd` | Querying the FSDB simulation dumps (`vcs -debug_access+all -kdb -lca` plus a `-ucli` do-file `$fsdbDumpvars`) | simulation-triage |
| `dc_shell`, and a **DC-Ultra** entitlement on the license server | Mapping. `dc_run.tcl` maps with `compile_ultra` and has no plain-`compile` path — the PPA targets are judged against DC-Ultra QoR, so a plain-`compile` fallback would be judged against numbers nobody asked for | synthesis |
| `pt_shell` | Timing and power analysis of the mapped netlist | timing-analysis, power-analysis |
| `LIB_DB` | The std-cell Liberty `.db` that mapping links against and that both analyses re-link | synthesis, timing-analysis, power-analysis |
| `LIB_V` | The std-cell Verilog models the gate-level run needs | power-analysis |
| `WIRE_LOAD_MODEL` | synthesis's interconnect estimate: a model the library carries, or `none`. Required without a default because a library declares neither, and the choice moves both numbers the stage is judged on | synthesis |
| `spyglass` | Lint and CDC goals | lint-cdc |

`specification`, `simulation-plan` and `rtl-design` need only the first row. Losing synthesis
costs timing-analysis and power-analysis too — both read the netlist it writes.

## Optional

| Variable | When to set | How |
|---|---|---|
| `VCS_CC` / `VCS_CPP` | Pin the C/C++ compiler when the host's default GCC produces objects incompatible with VCS's prebuilt non-PIC objects (typical symptom: link-time errors building `simv`). VeriPower passes them through conditionally via `${VCS_CC:+-cc "$VCS_CC"}` | `export VCS_CC=<gcc>` and `export VCS_CPP=<g++>` (e.g., `gcc-4.8`/`g++-4.8` is a known-good pairing for some VCS-on-modern-distro combinations) |

## Coverage report (urg text layout)

`simulation`'s structural-coverage gate parses the **text** report from `urg` (`dashboard.txt` +
`modlist.txt`) into `structural-coverage.json` (`parse_coverage.py`). Two things it needs:

- **`-format text`.** The parser reads urg's text tables; nothing reads the HTML.
- **`-report <dir>` and `--cov-dir` naming the same directory.** `-report` names where urg writes,
  not what it reports — the `coverage` target passes both on one line, so they agree by
  construction.

Which dim columns appear is not fixed. urg prints the columns it has, which follows the `-cm`
metrics compiled in (`VCS_COV`) and what the `.vdb` holds: a real run without branch coverage
prints five columns, and runs with covergroups print a `GROUP` column beside the structural ones.
The parser takes its columns from the header above each table, so a different set parses; a dim
urg did not measure is absent, and a requirements row bounding it fails by name rather than
being scored against something else.

## Convention

Keep all of the above in a site-level EDA env file sourced from your `~/.bashrc`.

## Troubleshooting

- **`/bin/sh` resolves to something other than `bash`** (e.g., `dash` on some Debian-family defaults): repoint with the distro's standard mechanism — on Debian/Ubuntu that is `sudo dpkg-reconfigure dash` answered "No".
- **Variable looks unset:** first run `echo $VAR_NAME` to confirm. If it's set, trust it — do **not** fall through to filesystem search. Only when genuinely unset, locate the path via `find` or by reading the example paths in stage `env.sh` comments.
