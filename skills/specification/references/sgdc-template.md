# SGDC — generated-output reference

`constraints/<TOP>.sgdc` is **generated** by the `derive-constraints` verb from `clocks.json` +
`top-io.json`. Do **not** hand-edit; change the source and re-run derive.

**Emitted (spec-time):**
- `current_design <TOP>`.
- `clock -name <clk> -period <T> -edge {0 T/2}` per non-generated `clocks.json` entry (period
  equals `<TOP>.sdc`'s by construction — same entry, two emitters), plus `-domain <D>` when
  `clocks.json` has ≥1 `async` clock and ≥2 non-generated
  clocks: all `primary`/`synchronous-related` clocks share one domain name (`sync`), each `async`
  clock gets its own distinct domain (its own name); the generator fails loudly if an `async` clock
  is literally named `sync` while synchronous clocks exist (name-collision guard). SGDC-native equivalent of `<TOP>.sdc`'s
  `set_clock_groups -asynchronous` — SpyGlass's SGDC parser rejects `set_clock_groups` itself
  as an unknown command (confirmed on SpyGlass_vL-2016.06: `tests/eda/f1-sgdc-clock-group/`).
- For each `top-io.json` `role: reset` port: `reset -name <p> -value <reset_polarity>` with `-async`
  iff `ResetKind=async`, plus `abstract_port -ports <p> -clock <Clock Domain> -reset <p>`.
  A DUT with no `Role=reset` port emits no reset section.
- `abstract_port -ports {…} -clock <Clock Domain>` per `Role=data` port, grouped by domain
  (cross-domain ports associate with the driver domain — the `clock_domain` value).

**Deferred to RTL (consumer side):** `quasi_static`, `sync_cell`, `reset_synchronizer`,
`set_case_analysis`.
