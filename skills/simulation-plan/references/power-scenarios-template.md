# Standard 9-Power-Scenarios Template

Load this template, materialize it per the module, and write the result into the `verification-plan.md` power section and `power-scenarios.json`.

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

## Per-module materialization guide

Materialize each scenario's abstract description ("business flow," "low power," "DVFS switching," etc.) into an executable sequence per this module's specification. The result goes in **one** place — `power-scenarios.json` — with one entry per scenario:

```json
{
  "id": "S4a",
  "scenario": "200MB/s (low-power off)",
  "clock_state": "on",
  "reset_state": "de-asserted",
  "data_state": "business_flow",
  "low_power_state": "off",
  "corner_intent": "TT",
  "sequence_ref": "<module>_traffic_200mbps_seq",
  "duration_cycles": 10000,
  "purpose": "Typical performance"
}
```

`verification-plan.md` §4 points here and restates no field. What belongs in §4 is what an entry
cannot hold: which module signals the low-power states drive, the DVFS frequency bands `switching`
means for this module, and why a scenario was materialized the way it was.

## RTL-equivalent scenario deduplication

Some scenarios produce identical RTL-layer stimulus and differ only in corner — a typical example is S1 (SS/125C, clock=off) and S7 (FF/125C, clock=off), both reduce on RTL to "clock=off + no traffic." This template requires you to **keep independent IDs and `corner_intent`** but **reuse the same `sequence_ref`**. Consumers group by `sequence_ref` at execution time, run each group only once, but produce a SAIF per ID (via hardlinks); later tools annotate by `corner_intent`.

## Role of corner annotation

Corner (SS / TT / FF + temperature) **does not affect RTL simulation behavior** — RTL simulation is corner-agnostic. Corner is plan-layer annotation metadata, consumed by power-analysis tools (e.g., PrimeTime PX). At the RTL stage, its only role is:
- Telling the consumer "which corner this SAIF should be interpreted under."
- Guiding you on which scenarios need independent stimulus vs. which are corner variants only.

## Handling missing scenarios

When the specification mentions a low-power feature (e.g., retention mode) that the standard 9-scenarios template does not cover, you should append supplementary scenarios (named S8, S9, …) at the end of `verification-plan.md` §4 and sync them into `power-scenarios.json`.

## `sequence_ref` naming rules and `sequences[]` sync (cross-stage contract)

`power_scenarios[].sequence_ref` is a reference into `sequences[].name` — not an independent namespace. SV classes are materialized only from `sequences[]`, so `check-scaffold` rejects a `sequence_ref` that resolves to no `sequences[].name` (and downstream, no SV class would exist for it).

| Situation | How to fill |
|---|---|
| Power scenario stimulus equals some functional sequence | `sequence_ref` = that functional sequence's `sequences[].name`. |
| Power scenario needs independent stimulus (typical: clock-off / sustained idle / sustained saturated traffic / DVFS switching) | First add a new entry to `sequences[]` (with `name` + `agent`), then have `power_scenarios[].sequence_ref` reference that `name`. |

`sequences[]` is the materialization list (functional + power union); `tests[]` and `power_scenarios[]` are consumption indices — they share the same materialization pool.
