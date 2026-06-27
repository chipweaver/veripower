# SGDC — generated-output reference

`constraints/<TOP>.sgdc` is **generated** by the `derive-constraints` verb from `design.md` §1.6 +
§1.4.1. Do **not** hand-edit; change the design tables and re-run derive.

**Emitted (spec-time):**
- `current_design <TOP>`.
- `clock -name <clk> -period <T> -edge {0 T/2}` per non-generated §1.6 clock (period must
  equal `<TOP>.sdc`).
- For each §1.4.1 `Role=reset` port: `reset -name <p> -value <ResetPolarity>` with `-async`
  iff `ResetKind=async`, plus `abstract_port -ports <p> -clock <Clock Domain> -reset <p>`.
  A DUT with no `Role=reset` port emits no reset section.
- `abstract_port -ports {…} -clock <Clock Domain>` per `Role=data` port, grouped by domain
  (cross-domain ports associate with the driver domain — the §1.4.1 Clock Domain value).

**Deferred to RTL (consumer side):** `quasi_static`, `sync_cell`, `reset_synchronizer`,
`set_case_analysis`.
