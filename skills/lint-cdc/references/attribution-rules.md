# Attribution rules — which rule family means whose artifact

Applies to: every `severity=error` violation you triage in Step 4 / Step 5, and to the
`--fix-owner` you pass to the combiner in Step 6.

## Why this file exists

**The line a violation is reported at is not always the line that must change.** SpyGlass
reports where it *noticed* the problem, which for a whole class of rules is the RTL that used
something nobody declared. Blaming that file sends a rework round to a stage that cannot fix it.

The rule family is what separates the two situations. Nothing else in the report does: the file,
the line, and the severity are identical in both.

## The two situations

### A declaration is missing

Families: `Clock_*`, `Reset_*`, `SGDC_*`, `Setup_*`, `Ac_unclocked*`

The RTL may be entirely correct. What is absent is a `clock -name`, a reset constraint, or a
case value — either in the depth annotations this stage carries (`{workdir}/scripts/constraints.sgdc`)
or in the spec's seed (`<sgdc_seed>/constraints/<TOP>.sgdc`).

**Check the SGDC before the RTL, in that order:**

1. Does the declaration belong in the accumulated depth annotations you carry? Then it is yours:
   add it in Step 4/5, re-run, and this never becomes a failure at all.
2. Does the spec's own seed lack it? Then name `specification`.

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

## A family not listed here

Read the message and decide which of the two situations it is. If it does not resolve to either,
**omit `--fix-owner`**: an unnamed owner brings a human in, while a wrong one spends a whole
rework round on a stage that cannot fix it. Do not extrapolate from a prefix that merely looks
similar — `Ac_unclocked*` sits with the declaration family while every other `Ac_*` sits with the
defect family, so the prefix shape alone is not the signal.

## Extending this file

Add a family here only from observed behavior, and record what you observed: the rule id, the
policy and goal it fired under, the SpyGlass version, and what the fix turned out to be. A family
placed here by inference rather than measurement is worse than an absent one, because an absent
family escalates to a human while a wrong one routes confidently.
