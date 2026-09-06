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

| Required | Purpose | Sanity check |
|---|---|---|
| `dc_shell` / `pt_shell` / `vcs` / `spyglass` on `PATH` | Stage Makefiles and scripts invoke directly | `which dc_shell` |
| `fsdbreport` / `fsdb2vcd` on `PATH` | simulation dumps FSDB (`vcs -debug_access+all -kdb -lca` + `-ucli` do-file `$fsdbDumpvars`); simulation-triage queries it (`fsdbreport`) | `which fsdbreport` |
| `LM_LICENSE_FILE` and/or `SNPSLMD_LICENSE_FILE` | Synopsys license server checkout (tools read these at launch; VeriPower does not validate) | `lmstat -c "$LM_LICENSE_FILE"` |
| A **DC-Ultra** entitlement on that server | `dc_run.tcl` maps with `compile_ultra` and has no plain-`compile` path — the PPA targets are judged against DC-Ultra QoR | run the `env-precheck` skill's Design Compiler smoke row |
| `LIB_DB`, `LIB_V` | synthesis / power-analysis read std-cell libs | stage `env.sh` `:?` guard fires on miss |
| `WIRE_LOAD_MODEL` | synthesis's interconnect estimate: a model the library carries, or `none`. Required without a default because a library declares neither, and the choice moves both numbers the stage is judged on | `env.sh` `:?` guard fires on miss; `dc_run.tcl` aborts when the reports disagree with what was asked for, either way |
| `UVM_HOME` | simulation / power-analysis compile UVM DPI | same |
| `python3` >= 3.10 with `jsonschema` >= 4.18, `referencing`, `PyYAML` | framework state tool and stage gates validate result/review schemas (`registry=`-based `$ref` resolution needs the post-4.18 jsonschema API); the stage CLIs annotate `list[str] | None` in evaluated signature position, which is a TypeError before 3.10 | `python3 -c "import sys, jsonschema, referencing, yaml; assert sys.version_info >= (3, 10)"` |
| `/bin/sh` → `bash` **where VCS runs** | The VCS launcher is `#!/bin/sh -h` and relies on bash semantics. That is the machine the launcher executes on, which is not always the one you type on: with a containerized install the host's `/bin/sh` can be `dash` and every stage still runs | `readlink -f /bin/sh` there, not necessarily here |

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
