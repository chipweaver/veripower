---
name: timing-analysis
description: Assess post-synthesis setup and hold timing with PrimeTime and determine what the evidence establishes under the task's constraints.
---

# Static Timing Analysis

Assess the implementation under the required timing conditions. Read `dispatch.json`, original intent,
requirements, the synthesized netlist and SDC, and the materials carried into `{workdir}`. Determine the necessary
work from what changed. An existing report may support a new judgment when its implementation,
conditions and analysis scope still apply. The implementation input is the complete synthesis
`out/` directory, including supporting constraints; a changed package calls for reassessment.

Write under `{workdir}`; upstream inputs remain read-only. The framework carries previously
published setup and products into this directory, without the old verdict. Keep useful analysis
and comparison material in `evidence/`.

## Tools

`<skill>` is this skill's directory. Prepare missing editable setup when needed:

```bash
python3 <skill>/scripts/timing/__main__.py bootstrap --workdir {workdir}
```

Bootstrap locates the netlist and matching SDC, installs missing `run_sta.tcl` and `config.tcl`, and
preserves authored files. Set the actual cell library as `LIB_DB` in `config.tcl` and inspect the calculation
settings. Run the required analysis:

```bash
cd {workdir}
python3 <skill>/scripts/timing/__main__.py run --workdir .
```

The entrypoint computes in a temporary directory using the current setup. Scripts write outputs
relative to their working directory: `timing-report.txt` and any supplementary `reports/` tree.
Old reports are withdrawn and replaced only after successful,
readable output. The log and failed calculation remain available until retry. Wait for completion
and inspect warnings, effective constraints and the libraries used.

## Judge and close

Review the reported endpoints, port delays, clocks and untested reasons against the task and
applicable exceptions. These native reports are in `timing-report.txt`; the CLI's setup/hold
measurements cover the reported paths, not the completeness or validity of the analysis scope.
`report_units` in the same report supplies the conversion to ns.
Numerical `timing_slack_ns` rows compare the minimum worst setup/hold slack with their own bounds;
VIOLATED identifies negative slack even when displayed as zero. Overall STA acceptance separately
requires both directions to be MET. Give evidence-based judgments for other timing requirements.

```bash
python3 <skill>/scripts/timing/__main__.py finalize --workdir {workdir} \
  [--requirements '[{"id":"R-1","met":true,"actual":"measured value","measured":"report and scope"}]'] \
  [--fail-reason "unresolved cause"] [--fix-owner <rule>]
```

Use `--fail-reason` for invalid or incomplete analysis even if a report contains numbers. Name the
owner from the defect: local analysis errors belong here; incorrect implementation or constraints
belong to their producer. Resolve local problems and retry the affected work. Acceptance changes
follow the user's actual authorization.

Finalize withdraws the previous result before judging. Exit 0 means a pass/fail result was written;
return `STATUS: DONE`. On a nonzero exit, resolve the cause or return `STATUS: BLOCKED <cause>`.
