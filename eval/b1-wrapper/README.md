# B1 bare EDA tool wrapper

Public, manual-level entry points to the Synopsys EDA tools (VCS/UVM,
Design Compiler, PrimeTime, SpyGlass, urg) — the same tools and the same
standard flags any engineer would use from the tool manuals. **This wrapper
contains no VeriPower orchestration, gates, or result-file plumbing, and
nothing specific to any evaluated design.** You bring your own inputs and you
decide when to run what, how to iterate, and how to self-check. There is no
pipeline, no gate, no orchestration here.

## You provide (per design)

- **RTL** + a `filelist.f` (VCS/DC) and `filelist.txt` (SpyGlass sourcelist).
- **Your own UVM testbench** with your own pass/fail signal (e.g. UVM error
  count / sim exit code). The official golden model is held out — write your
  own functional checks.
- **Constraints**: `constraints/example.{sdc,sgdc}` are generic single-clock
  skeletons — replace with your design's real clocks/resets/ports.
- **Environment**: export `LIB_DB` (std-cell `.db`), `LIB_V`, `UVM_HOME`, and
  set `TOP`. See `../../docs/eda-env.md` for the full tool/license/OS matrix.

## Targets (flat — no cross-stage dependency; you sequence them)

| `make` target | Tool | Needs |
|---|---|---|
| `lint` / `cdc` | `spyglass` | `filelist.txt` + `constraints/example.sgdc` |
| `synth` | `dc_shell` | `FILELIST` (RTL manifest, one path per line) + `SDC_IN` (default `constraints/example.sdc`) + `LIB_DB` → `out/<TOP>_syn.{v,sdc,sdf}` |
| `sta` | `pt_shell` | `out/<TOP>_syn.v` + `.sdc` + `LIB_DB` → `timing-report.txt` |
| `sim-compile` | `vcs` | `filelist.f` (RTL+TB) + `UVM_HOME` → `./simv` |
| `sim-run TEST=<t>` | `simv` | a compiled `./simv` |
| `coverage` / `merge` | `urg` | coverage dbs from sim runs |

## Demo

`demo/` holds a generic toy design (an 8-bit accumulator — unrelated to any
evaluated module) plus a minimal UVM TB, so you can see the expected input
layout and smoke a target, e.g.:

```
export LIB_DB=/path/to/stdcell.db TOP=accum
make synth FILELIST=demo/filelist.txt       # DC on RTL only (FILELIST is a manifest)
make lint                                    # SpyGlass (edit spyglass.prj top + filelist.txt)
```
