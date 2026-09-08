# RTL coding rules

Applies to every RTL file you write under `src/`. Standard RTL discipline is assumed and not
restated here — what follows is only what this flow's tools do that you would not otherwise know,
and the one judgment call that is yours.

## What the toolchain does to you

- **Strict Verilog-2001 only.** No gate decides this and the downstream tools would happily compile
  SystemVerilog, so it is on you. Nothing keys on the file extension.
- **A ROM's contents have to survive the synthesis reader.** A procedural `initial` block is the one
  way to fill a ROM that simulates correctly and synthesizes to nothing: `dc_shell` reports
  `Warning: … The statements in initial blocks are ignored. (VER-281)`, then constant-folds the
  combinational read and removes the array — the netlist has no ROM at all, RTL simulation still
  passes, and the first thing that notices is a gate-level run computing with zero contents. Use a
  `case` decode over the address, or `$readmemh` against a generated file. Measured on a delivered
  design, where it cost a power-analysis round, a triage round and an RTL rework round.
- **A synchronizer has to be its own module.** lint-cdc writes `sync_cell -name <module>` into the
  SGDC from the annotation you report, so the name must be a real module in the netlist; a
  synchronizer inlined into surrounding logic cannot be annotated at all. Same for tri-state
  drivers.
- **Includes must be declared.** Every downstream filelist is generated from `rtl-files.json`, so a
  header you `` `include `` through a path you did not report in `incdirs` compiles here and fails
  downstream.

## What you do not choose

Reset polarity and kind are `top-io.json`'s `reset_polarity` / `reset_kind`, per port. Read them
there. Async active-low is common, not required — and a wrong guess is not caught by any gate in
this flow until the netlist disagrees with the testbench.

## The one trade-off that is yours

Area and power optimisation are advisory: no gate checks them, and `synthesis` / `power-analysis`
only measure the outcome against the requirements rows they judge. So never trade away behaviour a
requirements row or `design.md` specifies in order to buy one — a deviation from stated intent
is what the intent reviewer is looking for, a missed optimisation is not.
