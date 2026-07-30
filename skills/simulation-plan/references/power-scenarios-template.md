# Standard 9-Power-Scenarios Template

Load this table, materialize each row for this module, and write the result into
`verification-plan.md` §4 and `power-scenarios.json`. No gate checks that a scenario came from
this set — `check-scaffold` only resolves `sequence_ref` — so loading the table first is the whole
discipline. Authoring from memory drops rows silently.

## Standard 9-scenarios table

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

## Where each row lands

The table's abstract columns are a statement about the module, not machine input: nothing reads
them, and reading them is a human's job. They go in `verification-plan.md` §4, next to the note
that says how the row was materialized — which signals `low power` drives on this module, what
frequency band `switching` means here, what stimulus `business flow` reduces to, and why a row was
dropped as inapplicable. A row you keep and a row you drop both need that sentence.

What crosses into `power-scenarios.json` is only what power-analysis reads:

```json
{"id": "S4a", "sequence_ref": "<module>_traffic_200mbps_seq",
 "duration_cycles": 10000, "corner_intent": "TT"}
```

## RTL-equivalent scenario deduplication

Some rows produce identical RTL-layer stimulus and differ only in corner — S1 (SS/125C, clock=off)
and S7 (FF/125C, clock=off) both reduce on RTL to "clock off + no traffic". Keep independent `id`
and `corner_intent`, and **reuse the same `sequence_ref`**: consumers group by `sequence_ref`, run
each group once, produce a SAIF per `id` (via hardlinks), and let later tools annotate by
`corner_intent`.

Corner (SS / TT / FF + temperature) does not affect RTL simulation behavior — RTL simulation is
corner-agnostic. `corner_intent` tells the consumer which corner the SAIF should be interpreted
under, and tells you which rows need their own stimulus versus which are corner variants of one.

## `sequence_ref` naming rules and `sequences[]` sync (cross-stage contract)

`power_scenarios[].sequence_ref` references `sequences[].name` — not an independent namespace. SV
classes are materialized only from `sequences[]`, so `check-scaffold` rejects a `sequence_ref`
resolving to no `sequences[].name` (and downstream, no SV class would exist for it).

| Situation | How to fill |
|---|---|
| Power scenario stimulus equals some functional sequence | `sequence_ref` = that functional sequence's `sequences[].name`. |
| Power scenario needs independent stimulus (typical: clock-off / sustained idle / sustained saturated traffic / DVFS switching) | First add a new entry to `sequences[]` (`name` + `agent`), then point `sequence_ref` at that `name`. |

`sequences[]` is the materialization list (functional + power union); `tests[]` and
`power_scenarios[]` are consumption indices into that one pool.
