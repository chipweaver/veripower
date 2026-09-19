---
name: power-analysis
description: Build and check power experiments, calculate averaged gate-level power with SAIF and PT-PX, and assess the results against the task's power requirements; not for functional regression or static timing analysis.
---

# Power Analysis

Establish the intended operating conditions, capture their activity, calculate power, and explain
what the measurement establishes. The supplied tools use gate-level simulation, SAIF and PT-PX
interval-average power; this does not establish instantaneous peak power or IR drop.

Read `{workdir}/dispatch.json` for input locations. `intent`, `design` and `requirements` give the
goals, design choices and budgets. Read both `plan/verification-plan.md` for measurement meaning
and `plan/power-scenarios.json` for identifiers. `netlist/out/` contains the implementation and
constraints; `tb_env` provides reusable verification sources, data, scripts and setup. Inspect what
you reuse, including any services behind a reference-model bridge. Write under `{workdir}`;
shared inputs remain read-only.

## Choose the work from the evidence

The framework carries published experiment sources, setup and measurements into `{workdir}`,
without the old verdict. Choose the work from changed inputs and the measurement being claimed.
Reuse artifacts whose implementation, conditions and scope still apply; a budget-only change can use existing reports.

For a new workdir, prepare editable setup (`<skill>` is this skill's directory):

```bash
python3 <skill>/scripts/power/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

Bootstrap resolves the netlist top and plan, and installs missing templates. It does not run tools
or require simulation inputs for a calculation-only task. Existing authored files survive rework;
check their settings against this round's inputs. Use the project's actual libraries and models.

From `{workdir}`, source `env.sh` and select the needed command:

```bash
. ./env.sh
python3 <skill>/scripts/power/__main__.py COMMAND --workdir .
```

| COMMAND | Work performed |
|---|---|
| `compile` | Build the authored experiment and check SDF annotation |
| `simulate` | Run planned scenarios using the existing executable |
| `calculate` | Read checked activity and calculate power in a fresh PT process per scenario |

These commands are independent. They invalidate the artifacts they replace; interrupted calculations
cannot publish reports. Wait for processes to exit, fix local errors and retry the affected work.

## Build the experiment when needed

Author `experiment/compile.sh` and `experiment/run.sh`; both run from `{workdir}`. The compiler
script supplies the netlist, matching simulation models and SDF annotation. Put disposable build
intermediates in `work/`; keep inputs and reusable outputs outside it. Finalize publishes the other
workdir contents except framework files and execution scratch under `.pending/`. Inspect annotation
warnings for unmapped arcs or model mismatches. Choose suitable TB components; no UVM inheritance,
agent or DUT instance hierarchy is prescribed.

`run.sh <scenario-id> <absolute-saif-path> <absolute-status-path>` controls workload, initialization,
cooperating interfaces, clocks/resets, sampling and completion. Referenced helpers can manage data
and services. Reuse suitable drivers, reference models and checks directly. Adapt checks to the
measured behavior: idle need not have transactions, while an active workload must do useful work.
Check useful behavior against the task's expected outcomes.

Choose legal initialization and observation times from the measurement purpose and actual timing.
Check that capture covers the intended conditions and interval. Write `PASS` to the supplied status
path after the checks and SAIF capture complete; for UVM, account for report-server errors/fatals.
A zero simulator exit alone is not completion evidence.

## Calculate and interpret

`env.sh` supplies calculation inputs. Set `LIB_DB` to the Tcl list of linked `.db` paths and
`STRIP_PATH` to the captured DUT hierarchy using the SAIF separator. Adapt `scripts/ptpx.tcl` for
needed macro, constraint or operating-condition setup. The calculator consumes the netlist, library,
constraints and activity; SDF belongs to GLS. Review mapping, slew/load modeling and tool warnings
against the design. Nonzero annotation and a parsed number do not establish a valid measurement.

Activity and completion evidence are in `saif/<id>.{saif,status,run.log}`; calculation reports and
logs are in `reports_ptpx/<id>/`. Failed/interrupted calculation output remains under `.pending/`.
Explain the measured conditions, checks, results and limits concisely in `analysis.md`, referencing
the original evidence. No budget means a measurement report, not compliance with an invented limit.

## Close the stage

Finalize when this stage's work is complete, or when an unresolved issue must be returned to its
caller. Changes to acceptance meaning follow the user's actual authorization,
whether decided by a person or under delegation.

```bash
python3 <skill>/scripts/power/__main__.py finalize --workdir {workdir} \
  [--fail-reason "<unresolved cause>"] [--fix-owner <rule>] \
  [--requirements '[{"id":"R-1","met":true,"actual":"reported","measured":"analysis.md and reports_ptpx/idle/power_flat.rpt"}]']
```

Finalize checks completion and reports, reconciles components, and compares numerical `power_mw`
targets with the named scenario, or all scenarios if unnamed. Give evidence-based `--requirements`
verdicts for rows without numerical targets. Use `--fail-reason` for an invalid or incomplete
measurement even if reports contain numbers; the CLI cannot infer workload meaning.

Name `--fix-owner` from the evidence, including this stage for its own experiment or calculation.
Leave it unresolved when the cause is unknown.

Exit 0 means `result.json` was written, pass or fail; return `STATUS: DONE` and let the caller route
it. Exit 2 means closure failed; resolve the reported cause or return `STATUS: BLOCKED <cause>`.
