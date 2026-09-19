# Trace a lint or CDC finding to its source

A report can point at the RTL that uses a clock or reset whose declaration is wrong or missing.
Inspect the reported construct together with the effective SGDC before naming `--fix-owner`.

`scripts/constraints.sgdc` combines the specification seed and RTL constraint annotations;
bootstrap regenerates it. Compare a questionable declaration with those sources. A wrong boundary
definition belongs to specification, an incorrect RTL annotation to rtl-design, and a rendering or
local setup error to lint-cdc. Correct the source rather than masking it in generated SGDC.

`scripts/local.sgdc` owns analysis-specific port/clock/reset associations not supplied by the seed.
A missing association here can require local repair even when the report points at RTL. Inspect
inherited waivers against the current finding as well.

For a suspected structural defect, check the actual crossing and its constraints. A rule prefix or
source location alone does not establish the repair owner. Omit ownership only when the evidence
cannot settle it; the caller handles the unresolved attribution under the task's authorization.
