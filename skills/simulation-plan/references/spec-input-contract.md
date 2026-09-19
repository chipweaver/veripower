# From specification to the functional verification plan

Use the original intent and resolved design choices to determine expected behavior. The sidecars
provide the interface and check references consumed by simulation; they do not supersede the task
when a discrepancy is found. This guide describes the functional scaffold. Power measurements
are planned in verification-plan.md and implemented by power-analysis.

## Interfaces and agents

Assign the data-port `interface_group`s in `top-io.json` to agents. Each group must be claimed
exactly once; `check-scaffold` checks this partition. Choose active agents for interfaces requiring
stimulus and passive agents for observation. An agent can cover several appropriate groups.

Simulation derives signals and transaction fields from these assignments and the specification's
port names, widths and directions; do not copy the port declarations into the plan. It creates
clock generators from `clocks.json` and applies the declared reset polarity. Clock/reset-only
groups do not need an agent. A missing interface or clock definition is an upstream boundary
problem to resolve, not a reason to leave that part of the DUT undriven.

## Stimuli, tests and checks

Use `design.md`'s behavior and timing scenarios, together with the requirements, to identify stimuli,
expected outcomes and timing obligations. Organize functional sequences around reusable driving
behavior: a sequence may support several testpoints, and a scenario may require cooperating
sequences. Each sequence names the agent it drives. Tests select the needed sequences and suites.

`check-hints.json` links observations to requirements. Group checks into testpoints through
`testpoints[].covers[]`, and associate their stimuli through `testpoints[].seqs[]`. Simulation reads
the referenced checks and requirements directly; do not copy them into the scaffold. Cover each
check or explain an evidence-based exclusion. Reference-model inputs and scoreboard observation
must match the behavior being checked.

Rows judged by simulation define the functional verification work; rows judged by simulation-plan
can constrain the plan itself, such as its stimulus distribution or scope. A power requirement with
`target.scenario` must name an identifier present in power-scenarios.json; measurement meaning
belongs in the plan rather than a functional sequence binding.
