# Rule A: scaffold vs. semantics repair boundary

> **Decision standard:** "Does this code edit change the expected behavior described by the plan? If yes, no retry; end with `STATUS: BLOCKED <compile|smoke + locus>` (the orchestrator maps it to the `status=fail` envelope)."

## Repairable (scaffold / wiring)

When `make simv` / `make smoke` fails, you may repair the files below within a **combined** round count of `defaults.yaml.scaffold_repair_max_rounds` (compile + smoke **share** the same counter — it is not N rounds each):

- `tb/uvm/<module>/agent/<a>_agent.sv` — factory registration, sub-component instantiation, sequencer / driver / monitor connections.
- `tb/uvm/<module>/env/<m>_env.sv` — agent instantiation, analysis port connections, sequencer configuration.
- `tb/uvm/<module>/test/base_test.sv` — config_db set/get, env build_phase.
- `tb/uvm/<module>/top/<top>_tb_top.sv` — DUT instantiation, interface instantiation, initial reset sequence, `uvm_config_db#(virtual ...)` set.
- `pkg/tb_pkg.sv` — include order, imports.
- `filelist.f` — paths, `+incdir+`, file order.
- `Makefile` — vcs options, `+UVM_TESTNAME` default.

## Not repairable (semantics / expected behavior) — no retry; end with `STATUS: BLOCKED`

- `check_txn()` / scoreboard compare logic inside `tb/uvm/<module>/checker/<sb>.sv`.
- `predict()` / `reset()` / state machine inside `tb/uvm/<module>/refmodel/<rm>_rm.sv`.
- **Field semantics** and **constraint semantics** inside `tb/uvm/<module>/transaction/<a>_txn.sv` (a misspelled field name still counts as scaffold).
- Any behavioral detail the plan describes as "should be so."
- `verification-plan.md` and the plan sidecars (not TB code, but equally not modifiable — including `tb-scaffold.json`'s `testpoints[]` and `power-scenarios.json`).
- `rtl_filelist.f` — bootstrap derives it from `rtl-files.json` and overwrites it every round. A wrong RTL path, `+incdir+` or file order is a defect in that file, which only a rtl-design rework reaches.

## Decision flow

1. Read com.log / smoke log; locate the error's file:line.
2. Check whether the change at that location lands in the "repairable" list:
   - Yes → repair one round, re-run `make simv` / `make smoke`.
   - No → end the response with `STATUS: BLOCKED <compile|smoke> <semantic locus>` (the orchestrator maps it to the `status=fail` envelope with `failure_phase: <compile|smoke>` + `fail_reason`).
3. If compile + smoke combined have reached `defaults.yaml.scaffold_repair_max_rounds` rounds and still do not pass, end with `STATUS: BLOCKED <compile|smoke> <locus>` (use the first phase that did not pass; the orchestrator records `failure_phase: <compile|smoke>`).
