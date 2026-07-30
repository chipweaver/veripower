# Spec Sidecars → Simulation-Plan Objects

How the specification's authored JSON maps to the objects this stage authors: `agents` /
`sequences` / `tests` / `testpoints[]` / `power_scenarios[]`, and `verification-plan.md`. Each
sidecar's own field semantics live in its schema under `specification/references/`; this guide is
only the mapping.

**Scope boundary.** It stops at the JSON contract you author. Turning the scaffold into
SystemVerilog (driver / monitor bodies, RM `predict()`, scoreboard `check_txn`, reset) happens later
in the `simulation` stage (`skills/simulation/references/inlined-check-hints.md`). Do not add
SV-rendering claims here.

`design.md` and the per-child `<child>.md` are the single human source of truth; there is no
separate requirement-to-testpoint mapping document, and nothing derives the sidecars — there is no
intermediate cache to read instead of them.

---

## features.json → tests and feature-traceability testpoints

One `tests[]` entry per behaviour worth its own testcase, each naming the feature `id` it exercises
in `tests[].feature`. A feature's `happy_path` / `corner_cases` / `negative_cases` are the positive,
boundary and negative testcases to author from it; `coverage_intent` is the coverage model to reach
for when present. `materialize-scaffold` resolves `feature` to the feature's `name`, and that name
is what the Feature column of `case-results-summary.md` shows a human.

## top-io.json → agents and transactions

- Ports sharing an `interface_group` become one virtual interface and one agent. Grouping is by
  `interface_group`, never by `clock_domain`.
- A group's `direction` values decide the agent's `mode`: `active` for a group you drive, `passive`
  for one you only observe.
- clk/rst ports carry no `interface_group`: they bind through `primary_clock` / `reset`. Putting one
  in a group collides with the clk/rst port name at render time.
- `interface.signals` and `transaction.fields` are script-injected from this file — same names, same
  widths, clk/rst excluded from the transaction. materialize does not abstract, rename, or merge, so
  there is no `addr` / `data` / `rw` to invent.
- `protocol` is your reference for which sequence pattern to author (`APB3` / `AXI4` / `custom`).

`top-io.json` also carries `reset_polarity` / `reset_kind` / `encoding`; those are for the
specification stage's constraint generation and its reviewers, not for you.

## design.md §1.5 timing scenarios → sequences

One scenario row per `SC-NNN` id, next to the waveform it belongs to. Author one `sequences[]` entry
per id: the row's stimulus is the sequence body, its expected outcome and timing obligation become
the testpoint's check intent, and a negative-path row gets a negative testpoint. The waveform and
its phase-by-phase description carry the cycle-level detail a row cannot.

## check-hints/<child>.json → testpoints[].covers[]

One file per child declared in `manifest.json`; `check_id` is unique across all of them, which is why
they are aggregated before the coverage matrix is checked. You cluster the `check_id`s into
`testpoints[].covers[]` — that clustering is the only authored input here. `materialize-scaffold`
then fills each `testpoints[].inlined_check_hints[]` from those `covers[]`:
`implementation_detail` = `implementation_detail_verbatim` if present else the summary, plus
`observable` / `reference_rule` / `latency` / `reset_behavior` copied as metadata. How those hints
become SV `predict()` / scoreboard checks is the downstream `simulation` stage's job.

Non-target capabilities ("does not support" / "does not include") belong in a feature's
`negative_cases`, so negative tests and result summaries can be derived from them.

---

## Worked example: APB slave register module

Given `features.json` with `F-00` "APB slave interface" (`happy_path`: legal R/W transactions
complete; `corner_cases`: `pready` inserts wait cycles; `negative_cases`: illegal address access),
`top-io.json` grouping `psel / penable / pwrite / paddr / pwdata / prdata / pready / pslverr` under
`interface_group: APB` (with `pclk` / `preset_n` ungrouped, `role` clock / reset), §1.5 rows
`SC-APB-00` (legal write, `pready` within 1–2 cycles, `pslverr`=0) and `SC-APB-02` (illegal address,
`pslverr` high), and `check-hints/apb_slave.json` with `CHK-APB-00` (write→`reg_file[addr]`,
read→`prdata`) and `CHK-APB-01` (`pslverr <= (addr not in legal_range)`):

- **agents**: one `apb_agent`, `mode: active`, `interface_groups: ["APB"]`. Its signals and
  transaction fields are script-injected — the eight APB-group signals verbatim, `pclk` / `preset_n`
  excluded from the transaction and bound via `primary_clock` / `reset`.
- **sequences**: one entry per `SC-NNN` id, each naming `apb_agent`.
- **tests**: one per testcase from `F-00`, each with `feature: "F-00"`, its `seqs`, and its `suites`.
- **testpoints**: a positive one covering `CHK-APB-00` and a negative one covering `CHK-APB-01`.
  materialize fills their `inlined_check_hints[]` from `covers[]` — `implementation_detail` from
  each hint's `implementation_detail_verbatim`, with `observable` / `reference_rule` / `latency` /
  `reset_behavior` alongside.
