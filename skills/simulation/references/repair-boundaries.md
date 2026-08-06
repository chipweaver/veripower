# Rule A: scaffold vs. semantics repair boundary

When `make simv` or `make smoke` fails, one question decides what you do next:

> **Does the edit that would fix this change the behavior the plan describes?**

No, and it is wiring: repair it and re-run. Yes, and it is semantics: stop. Semantic errors do
not converge by retry, and the budget is not there to be spent finding that out.

Compile and smoke **share** one `defaults.yaml.scaffold_repair_max_rounds` counter; it is not N
rounds each. When it runs out, stop the same way, naming the first phase that did not pass.

Stopping means ending your response with `STATUS: BLOCKED <compile|smoke> <the semantic locus>`,
which the orchestrator routes out as `--failure-phase compile|smoke`.

## Where the line falls

Wiring is how the parts are connected: factory registration and sub-component construction in an
agent, analysis-port connections and sequencer configuration in the env, `config_db` set and get,
the clocking blocks and modports in an interface, VCS options in the `Makefile`. A misspelled
signal or field name is wiring too, however semantic the symbol sounds.

`tb_top.sv`, `tb_pkg.sv`, `filelist.f`, `tests/testlist.json` and the `*_signals.svh` /
`*_fields.svh` / `*_field_macros.svh` includes are **regenerated every round** from the plan and
`top-io.json`. Editing one is not forbidden so much as pointless — the next bootstrap overwrites
it — and it would be the wrong repair anyway: the clock set, the reset polarity, the DUT port
bindings and every vif signal are specification's declaration, so a TB that has them wrong means
that declaration is wrong and the fix routes there.

Semantics is what the design is expected to do: the compare in the scoreboard, `predict` and the
state machine in the refmodel, field and constraint meaning in a transaction, and anything the
plan states as should-be-so. Fixing one of those means deciding what correct is, which is the
plan's call and not yours.

Two things are not yours to edit at all, for reasons that have nothing to do with the line above.
`verification-plan.md` and the plan sidecars are the upstream intent. `rtl_filelist.f` is derived
from `rtl-files.json` and overwritten by `bootstrap` every round, so an edit to it does not
survive to the next one; a wrong RTL path there is an rtl-design defect and reaching it takes an
rtl-design rework.
