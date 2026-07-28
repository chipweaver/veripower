# SDC — generated-output reference

`constraints/<TOP>.sdc` is **generated** by the `derive-constraints` verb as a pure function of
`clocks.json` (clocks/relationships) + `design.md` §1.4.1 (port roles/domains). Do **not**
hand-author or hand-edit it; change the source and re-run derive. This file documents what derive
emits so reviewers know what to expect.

**Emitted (spec-time):**
- `create_clock -name <clk> -period <T> [get_ports <clk>]` per non-generated `clocks.json`
  entry (`T` = `period_ns`). Equality with `<TOP>.sgdc` is structural — both emitters render
  the same entry — and is asserted in `tests/unit/test_spec_constraints.py`, not re-checked at
  runtime by re-parsing the emitted text.
- `set_clock_groups -asynchronous` with one `-group` for the non-async (primary /
  synchronous-related) clocks plus one `-group` per `relationship: "async"` clock; emitted
  only when ≥2 non-generated clocks exist.
- `set_clock_uncertainty -setup 0.2 [all_clocks]` + `-hold 0.0 [all_clocks]` — fixed
  placeholders; the split form is deliberate (single-value widens pre-CTS hold into false
  hold-VIOLATED; pre-CTS hold = 0 is the convention).
- `set_input_delay`/`set_output_delay` at `T×0.3` for each §1.4.1 `Role=data` port,
  `-clock <Clock Domain>`. Clock/reset ports get none.

**Deferred to RTL-visible stages (lint-cdc / timing annotate back), NOT spec-time:**
`create_generated_clock` (for `Generated=yes` clocks — derive emits a `#`-comment placeholder),
`set_false_path` / `set_multicycle_path`, `set_drive` / `set_load`, accurate uncertainty.
