# Standard Power-Scenarios Template

Materialize every row below for this module.

| ID | Scenario | Clock | Reset | Data | Low power | Purpose |
|----|----------|-------|-------|------|-----------|---------|
| S1 | Leakage baseline | off | asserted | none | - | Leakage floor. |
| S2 | Clock-tree power | on | asserted | none | - | CTS evaluation. |
| S3a | Idle (low-power off) | on | de-asserted | no traffic | off | Standby baseline. |
| S3b | Idle (low-power on) | on | de-asserted | no traffic | on | Standby optimization. |
| S4a | 200MB/s (low-power off) | on | de-asserted | business flow | off | Typical performance. |
| S4b | 200MB/s (low-power on) | on | de-asserted | business flow | on | Typical signoff. |
| S5 | Peak / worst case | on | de-asserted | full-toggle | off | PDN / IR drop. |
| S6 | DVFS switching transient | switching | de-asserted | business flow | switching | di/dt. |

A row's abstract states are a claim about this module, so they go in `verification-plan.md` §4 with
the note that resolves them: which signals `low power` drives here, what frequency band `switching`
means, what stimulus `business flow` reduces to. The machine half goes in `power-scenarios.json` per
its schema. **A row you drop needs that note as much as a row you keep** — "this module has no
retention control, so S3b has nothing to switch" is the answer a reviewer is looking for, and no
gate will ask for it.

There is no PVT column, and a row is not a corner. `ptpx.tcl` loads one `LIB_DB` for the whole
batch, so every row is computed at the same operating condition and a row that differs from its
neighbour only in the corner it was *meant* for reports the identical number — measured on 5 runs
across 2 modules, where the leakage row and the high-temperature leakage row agreed to the digit.
A corner sweep is a second run of this stage against a second library, not a second row.

The rows that usually need stimulus no functional sequence provides are the clock-off ones,
sustained idle, sustained saturated traffic, and DVFS switching. Add the `sequences[]` entry first,
then point `sequence_ref` at its name. Two rows that reduce to the same `sequence_ref` **and** the
same low-power state are one measurement: declare one.
