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
| `UVM_HOME` | simulation / power-analysis compile UVM DPI | same |
| `python3` with `jsonschema` >= 4.18, `referencing`, `PyYAML` | framework state tool and stage gates validate result/review schemas (`registry=`-based `$ref` resolution needs the post-4.18 jsonschema API) | `python3 -c "import jsonschema, referencing, yaml"` |
| `/bin/sh` → `bash` | The VCS launcher uses `#!/bin/sh -h` and relies on bash semantics | `readlink /bin/sh` should resolve to `bash` |

## Optional

| Variable | When to set | How |
|---|---|---|
| `VCS_CC` / `VCS_CPP` | Pin the C/C++ compiler when the host's default GCC produces objects incompatible with VCS's prebuilt non-PIC objects (typical symptom: link-time errors building `simv`). VeriPower passes them through conditionally via `${VCS_CC:+-cc "$VCS_CC"}` | `export VCS_CC=<gcc>` and `export VCS_CPP=<g++>` (e.g., `gcc-4.8`/`g++-4.8` is a known-good pairing for some VCS-on-modern-distro combinations) |

## Coverage report (urg text layout)

`simulation`'s structural-coverage gate parses the **text** report from
`urg -report cov_merge -format text` (`cov_merge/dashboard.txt` + `modlist.txt`) into
`structural-coverage.json` (`parse_coverage.py`). The parser was developed and **verified against
urg L-2016.06**, whose layout is a fixed-column `SCORE LINE COND TOGGLE FSM BRANCH` block (`--` =
dim not applicable). VeriPower does not pin a urg release, but this text layout is
version-sensitive: a different urg major version may emit a different header/column layout, in
which case `parse_coverage.py` **fails loud** (it never fabricates a "coverage met" result) and
must be adjusted for that version. The report MODE matters — `-report both` / `-report struct_cov`
emit a covergroup `SCORE GROUP` table instead, which is **not** the structural report the gate
consumes; the gate's `coverage` target must use `-report cov_merge`.

## Convention

Keep all of the above in a site-level EDA env file sourced from your `~/.bashrc`.

## Troubleshooting

- **`/bin/sh` resolves to something other than `bash`** (e.g., `dash` on some Debian-family defaults): repoint with the distro's standard mechanism — on Debian/Ubuntu that is `sudo dpkg-reconfigure dash` answered "No".
- **Variable looks unset:** first run `echo $VAR_NAME` to confirm. If it's set, trust it — do **not** fall through to filesystem search. Only when genuinely unset, locate the path via `find` or by reading the example paths in stage `env.sh` comments.
