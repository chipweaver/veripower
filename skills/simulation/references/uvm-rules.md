# UVM Testbench Rules

Applies to: `**/*_pkg.sv`, `**/tb/**`

## Directory & Hierarchy

- Under `**/tb/**`, keep environment reusable: clear hierarchical separation of agent/driver/monitor/seq.
- Interface boundaries via virtual interface injection.
- Packages (`*_pkg.sv`): explicit type and import ordering — avoid wildcard imports that cause symbol pollution.

## UVM Conventions

- Factory-based component and sequence creation (`type_id::create`); `set_type_override` per project conventions.
- Each phase does only its own work: build/connect/end_of_elaboration/run must not accumulate unrelated side effects.
- Paired objections (raise/drop) at sequence/test level — avoid leaks or premature drop causing random termination.

## Reporting

- Mismatch / check failure MUST use `` `uvm_error `` (or a higher level such as `` `uvm_fatal ``), **not** `$fatal` — `$fatal` bypasses the UVM report server, causing the regression runner to miss the count and the scoreboard to terminate early.
