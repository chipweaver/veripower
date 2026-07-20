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
  A UVM `filelist.f` must begin with the two standard UVM-from-source lines —
  VCS finds the library through the filelist, not the compile flags (the
  `sim-compile` recipe only compiles the DPI). Without them `` `include
  "uvm_macros.svh" `` fails even with `UVM_HOME` exported:

  ```
  +incdir+${UVM_HOME}/src
  ${UVM_HOME}/src/uvm_pkg.sv
  ```
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
layout and smoke every target as-shipped, e.g.:

```
export LIB_DB=/path/to/stdcell.db UVM_HOME=/path/to/uvm TOP=accum
make synth FILELIST=demo/filelist.txt   # DC on RTL only (FILELIST is a manifest)
make lint                               # SpyGlass; root filelist.txt ships pointing at the demo RTL
make sim-compile FILELIST=demo/filelist.f   # VCS+UVM (demo filelist.f carries the UVM lines)
make sim-run TEST=demo_test             # run the compiled ./simv
```

The root `filelist.txt` is the SpyGlass sourcelist `scripts/spyglass.prj` reads
(RTL only); replace it — and `spyglass.prj`'s `top` — with your design's.
