# SDC — generated-output reference

`constraints/<TOP>.sdc` is **generated** by the `derive-constraints` verb as a pure function of
`design.md` §1.6 (clocks/relationships) + §1.4.1 (port roles/domains). Do **not** hand-author
or hand-edit it; change the design tables and re-run derive. This file documents what derive
emits so reviewers know what to expect.

**Emitted (spec-time):**
- `create_clock -name <clk> -period <T> [get_ports <clk>]` per non-generated §1.6 clock
  (`T` = `SDC Period (ns)`; must equal `<TOP>.sgdc`).
- `set_clock_groups -asynchronous` with one `-group` for the non-async (primary /
  synchronous-related) clocks plus one `-group` per `Relationship=async` clock; emitted
  only when ≥2 non-generated clocks exist.
- `set_clock_uncertainty -setup 0.2 [all_clocks]` + `-hold 0.0 [all_clocks]` — fixed
  placeholders; the split form is deliberate (single-value widens pre-CTS hold → false
  hold-VIOLATED; pre-CTS hold = 0 is the convention).
- `set_input_delay`/`set_output_delay` at `T×0.3` for each §1.4.1 `Role=data` port,
  `-clock <Clock Domain>`. Clock/reset ports get none.

**Deferred to RTL-visible stages (lint-cdc / timing annotate back), NOT spec-time:**
`create_generated_clock` (for `Generated=yes` clocks — derive emits a `#`-comment placeholder),
`set_false_path` / `set_multicycle_path`, `set_drive` / `set_load`, accurate uncertainty.
