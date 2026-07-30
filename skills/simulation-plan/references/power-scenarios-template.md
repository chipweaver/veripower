# Standard 9-Power-Scenarios Template

Materialize every row below for this module.

| ID | Scenario | Clock | Reset | Data | Low power | Corner | Purpose |
|----|----------|-------|-------|------|-----------|--------|---------|
| S1 | Static leakage | off | asserted | none | - | SS/125C | Leakage baseline. |
| S2 | Clock-tree power | on | asserted | none | - | TT | CTS evaluation. |
| S3a | Idle (low-power off) | on | de-asserted | no traffic | off | TT | Standby baseline. |
| S3b | Idle (low-power on) | on | de-asserted | no traffic | on | TT | Standby optimization. |
| S4a | 200MB/s (low-power off) | on | de-asserted | business flow | off | TT | Typical performance. |
| S4b | 200MB/s (low-power on) | on | de-asserted | business flow | on | TT | Typical signoff. |
| S5 | Peak / worst case | on | de-asserted | full-toggle | off | FF/125C | PDN / IR drop. |
| S6 | DVFS switching transient | switching | de-asserted | business flow | switching | TT | di/dt. |
| S7 | High-temperature leakage | off | asserted | none | - | FF/125C | Worst leakage. |

A row's abstract states are a claim about this module, so they go in `verification-plan.md` §4 with
the note that resolves them: which signals `low power` drives here, what frequency band `switching`
means, what stimulus `business flow` reduces to. The machine half goes in `power-scenarios.json` per
its schema. **A row you drop needs that note as much as a row you keep** — "this module has no
retention control, so S3b has nothing to switch" is the answer a reviewer is looking for, and no
gate will ask for it.

Rows that reduce to the same RTL stimulus share one `sequence_ref` and stay distinct by `id` and
`corner_intent` — S1 and S7 are the standing example: clock off, no traffic, different corner only.

The rows that usually need stimulus no functional sequence provides are the clock-off ones,
sustained idle, sustained saturated traffic, and DVFS switching. Add the `sequences[]` entry first,
then point `sequence_ref` at its name.
