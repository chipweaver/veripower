# Build or repair the simulation environment

The stage owner assigns the work scope and input paths. Read the current plan, requirements,
check hints, interface/clock definitions and relevant original intent. Existing TB code and failure
artifacts may already be in `{workdir}`; preserve unaffected work. Write only under that directory.

When setup or generated structure needs updating:

```bash
python3 <skill>/scripts/sim/__main__.py bootstrap --workdir {workdir} --plan <scaffold>
```

Bootstrap regenerates plan/boundary-derived interfaces, transactions, top, package and file/test
lists, while retaining authored drivers, checks, models and sequences. Reconcile changed ports with
clocking blocks/modports and changed agents with the environment; successful compilation alone
does not establish that new interfaces are driven or observed.

Implement checks using [authoring-checks.md](authoring-checks.md). Inspect code and scripts as
needed to understand a failure. Expected results come from the task's independent reference;
reading RTL for diagnosis does not make it the reference. Resolve local wiring, stimulus and check
errors. If the defect is upstream, report its evidence and the affected behavior to the stage owner.

Compile changed sources with `make simv`, run relevant smoke tests with `make smoke`, and check
materialization:

```bash
python3 <skill>/scripts/sim/__main__.py check-materialization --workdir {workdir} --plan <scaffold>
```

The presence check does not establish semantic adequacy. Report the actual compile/test results
and remaining issues, with log paths; no results is incomplete execution, not a known root cause.
Return `STATUS: DONE` when the assigned work is complete or `STATUS: BLOCKED <cause>` when it could
not be completed. The stage owner investigates and decides whether local work can continue.
Do not invoke kernel state transitions or dispatch further work.
