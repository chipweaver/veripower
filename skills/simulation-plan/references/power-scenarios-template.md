# Standard 9-Power-Scenarios Template

Load this template under **first-run** and **incremental-update** (specification field change) modes, materialize it per the module, and write the result into the `verification-plan.md` power section and `scaffold-specification.json.power_scenarios`.

## Standard 9-scenarios table

| ID | Scenario | Clock | Reset | Data | Low power | Corner | Purpose |
|----|----------|-------|-------|------|-----------|--------|---------|
| S1 | Static leakage | off | reset | none | - | SS/125C | Leakage baseline. |
| S2 | Clock-tree power | on | reset | none | - | TT | CTS evaluation. |
| S3a | Idle (low-power off) | on | de-asserted | no traffic | off | TT | Standby baseline. |
| S3b | Idle (low-power on) | on | de-asserted | no traffic | on | TT | Standby optimization. |
| S4a | 200MB/s (low-power off) | on | de-asserted | business flow | off | TT | Typical performance. |
| S4b | 200MB/s (low-power on) | on | de-asserted | business flow | on | TT | Typical signoff. |
| S5 | Peak / worst case | on | de-asserted | full-toggle | off | FF/125C | PDN / IR drop. |
| S6 | DVFS switching transient | switching | de-asserted | business flow | switching | TT | di/dt. |
| S7 | High-temperature leakage | off | reset | none | - | FF/125C | Worst leakage. |

## Per-module materialization guide

Materialize each scenario's abstract description ("business flow," "low power," "DVFS switching," etc.) into an executable sequence per this module's specification. Write the result into **both** copies in sync:

1. **`verification-plan.md` §4 9-Power-Scenarios Materialization** — human-readable review material; keep the 9-row table plus a per-row "materialization notes" paragraph (actual reset sequence name, transaction rate and sequence for business_flow, low-power signal names, DVFS frequency bands).

2. **`scaffold-specification.json.power_scenarios`** — machine-read contract; each entry takes the form:

```json
{
  "id": "S4a",
  "scenario": "200MB/s (low-power off)",
  "clock_state": "on",
  "reset_state": "released",
  "data_state": "business_flow",
  "low_power_state": "off",
  "corner_intent": "TT@25C",
  "sequence_ref": "<module>_traffic_200mbps_seq",
  "duration_cycles": 10000,
  "purpose": "Typical performance"
}
```

The two copies must correspond one-to-one — same number of entries, matching row IDs.

## RTL-equivalent scenario deduplication

Some scenarios produce identical RTL-layer stimulus and differ only in corner — a typical example is S1 (SS/125C, clock=off) and S7 (FF/125C, clock=off), both reduce on RTL to "clock=off + no traffic." This template requires you to **keep independent IDs and `corner_intent`** but **reuse the same `sequence_ref`**. Consumers group by `sequence_ref` at execution time, run each group only once, but produce a SAIF per ID (via hardlinks); later tools annotate by `corner_intent`.

## Role of corner annotation

Corner (SS / TT / FF + temperature) **does not affect RTL simulation behavior** — RTL simulation is corner-agnostic. Corner is plan-layer annotation metadata, consumed by power-analysis tools (e.g., PrimeTime PX). At the RTL stage, its only role is:
- Telling the consumer "which corner this SAIF should be interpreted under."
- Guiding you on which scenarios need independent stimulus vs. which are corner variants only.

## Handling missing scenarios

When the specification mentions a low-power feature (e.g., retention mode) that the standard 9-scenarios template does not cover, you should append supplementary scenarios (named S8, S9, …) at the end of `verification-plan.md` §4 and sync them into `scaffold-specification.json.power_scenarios`.

## `sequence_ref` naming rules and `sequences[]` sync (cross-stage contract)

`power_scenarios[].sequence_ref` is a reference into `sequences[].name`; **it is not an independent namespace.**

SV classes (`tb/uvm/seq/{module}_{name}_seq.sv`, compiled into `{module}_tb_pkg`) are materialized only from `sequences[]` — `power_scenarios[]` is **not** a materialization source. The downstream power-scenario emit resolves `power_scenarios[].sequence_ref` against the already-materialized `{module}_<sequence_ref>_seq` classes — if the ref is not registered in `sequences[]`, no SV class is materialized for it, so emit validation fails closed.

| Situation | How to fill |
|---|---|
| Power scenario stimulus equals some functional sequence | `sequence_ref` = that functional sequence's `sequences[].name`. |
| Power scenario needs independent stimulus (typical: clock-off / sustained idle / sustained saturated traffic / DVFS switching) | First add a new entry to `sequences[]` (with `name` + `agent`), then have `power_scenarios[].sequence_ref` reference that `name`. |

**Forbidden:** inventing a new `sequence_ref` name **without syncing the same name into `sequences[]`** — without a backing `sequences[]` entry no SV class is materialized for it, so emit validation always fails.

The template example name `<module>_traffic_200mbps_seq` and the like remain compliant — provided they are **simultaneously** registered as a `sequences[].name` entry (with the corresponding agent). Naming independence ≠ registration optional.

`sequences[]` is the materialization list (functional + power union); `tests[]` and `power_scenarios[]` are consumption indices — they share the same materialization pool.
