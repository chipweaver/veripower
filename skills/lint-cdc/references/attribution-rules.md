# Attribution rules — which rule family means whose artifact

Applies to the `--fix-owner` you pass to `finalize` when a run fails.

## Why this file exists

**The line a violation is reported at is not always the line that must change.** SpyGlass
reports where it *noticed* the problem, which for a whole class of rules is the RTL that used
something nobody declared. Blaming that file sends a rework round to a stage that cannot fix it.

For those families the rule id is the only thing that separates the two cases: the file, the
line, and the severity read identically. That is the whole job of this file, and it is why it
lists families rather than trying to be a decision table for the report as a whole.

## The two families where the report misleads

### A declaration is missing

Families: `Clock_*`, `Reset_*`, `SGDC_*`, `Setup_*`, `Ac_unclocked*`

The RTL may be entirely correct. What is absent is a `clock -name`, a reset constraint, or a
case value. Check the SGDC before the RTL, and in this order, because only the first case is
yours to fix:

1. Does the annotations sidecar declare it while `{workdir}/scripts/constraints.sgdc` lacks it?
   Then you missed it transcribing: add it, re-run, and this never becomes a failure at all.
2. Does the sidecar not declare it, though the RTL implies it? Then name `rtl-design`, whose
   authors own that claim. Adding it here instead would leave synthesis without the SDC half.
3. Does the spec's own seed lack a clock, reset or port association? Then name `specification`.

*Measured on SpyGlass `vL-2016.06`*: a `clk2` used in the RTL but never `clock -name`d in the
SGDC surfaces as `Clock_info03a` + `Setup_port01`, both pointing at the RTL file and line that
used `clk2`. Neither names the SGDC that should have declared it.

### A real structural defect

Families: `Ac_unsync*`, `Ac_conv*`, `Ac_glitch*`, `Ac_sync*`, `Reconvergence*`, and the ordinary
`W###` lint rules.

The reported file is the file to fix. Name `rtl-design`.

*Measured on SpyGlass `vL-2016.06`* (`tests/eda/f1-sgdc-clock-group/`): an unsynchronized
single-flop crossing is flagged as `Ac_unsync01` under policy `clock-reset`, goal
`cdc/cdc_verify_struct`.

Do not extrapolate from a prefix that merely looks similar: `Ac_unclocked*` sits with the
declaration family while every other `Ac_*` sits with the defect family, so the prefix shape
alone is not the signal.

## A family not listed here

Most rules are not in either family and do not need to be. Read the message and name the stage
whose artifact must change, the same as you would for a listed family; a rule absent from this
file is absent because nobody has needed to catalogue it, not because it is unattributable.
An elaboration or Design-Read fatal, for one, usually names a file the RTL could not find, and
the owner follows from the message directly.

**Omit `--fix-owner` only when you cannot name an owner at all** — not when the family is
missing here. An unnamed owner brings a human in, which is right when you genuinely do not know
and pure cost when you do.

## Extending this file

Add a family here only from observed behavior, and record what you observed: the rule id, the
policy and goal it fired under, the SpyGlass version, and what the fix turned out to be. A family
placed here by inference rather than measurement is worse than an absent one, because an absent
family escalates to a human while a wrong one routes confidently.
