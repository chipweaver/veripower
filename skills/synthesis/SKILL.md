---
name: synthesis
description: Establish the synthesized implementation, its constraints and measurements, and assess them against the task's requirements.
---

# Synthesis

Establish the implementation and evidence needed for the current task. Read `dispatch.json`,
the original intent, requirements, RTL and constraints, and the materials carried into `{workdir}`. A new dispatch
requires a current conclusion; it does not prescribe a new synthesis. Use measurements whose
implementation, conditions and scope still apply, and perform the work the remaining questions need.

Write under `{workdir}`; upstream inputs remain read-only. The framework carries previously
published setup and products into this directory, without the old verdict. Keep useful analysis
and comparison material in `evidence/`.

## Tools

`<skill>` is this skill's directory. Setup, execution and judgment are independent operations:

```bash
python3 <skill>/scripts/synthesis/__main__.py bootstrap --workdir {workdir}
```

Bootstrap refreshes `scripts/rtl_load.tcl` and `constraints.sdc` from upstream inputs. It installs
missing `config.tcl`, `constraints.local.sdc` and driver scripts, preserving existing copies of these
editable files. `manifest.module` supplies the top; `rtl-files.json` supplies source order and include
paths. Adapt `scripts/dc_run.tcl` for the required calculation. The supplied script maps
RTL using DC-Ultra; examining an existing mapped implementation may require different tool work.

Render the design's declared generated clocks and timing exceptions from
`constraint-annotations.json` into `constraints.local.sdc`, which follows `constraints.sdc`.
Check names and divider ratios against RTL. Record the engineering basis for exceptions, local
clock uncertainty and library-specific IO settings alongside the SDC commands.

Set the actual `LIB_DB` and `WIRE_LOAD_MODEL` (a library model or `none`) in `config.tcl`, then run:

```bash
cd {workdir}
python3 <skill>/scripts/synthesis/__main__.py run --workdir .
```

`run` computes in a temporary directory using the current setup. Scripts write outputs relative
to `out/` and `reports/` in their working directory, including supplementary reports, and read
inputs at explicit paths. Existing reports are withdrawn;
`out/` and `reports/` are replaced only after successful, readable output. The log and failed
calculation remain available until retry. Wait for completion and inspect warnings and conditions.

## Judge and close

Use current requirements with the applicable reports. `finalize` compares `area_um2` and
`timing_slack_ns` targets; setup slack comes from the high-precision `timing_setup.rpt`, whose
`report_units` output supplies the conversion to ns. QOR checks consistency. Refresh a report lacking
units or sufficient precision from the applicable
implementation and constraints; that alone does not require resynthesis. Declare evidence-based
judgments for synthesis rows without numerical targets, including library-based equivalent-gate units.
Numeric targets cannot be overridden by declarations.

```bash
python3 <skill>/scripts/synthesis/__main__.py finalize --workdir {workdir} \
  [--requirements '[{"id":"R-1","met":true,"actual":"measured value","measured":"report and scope"}]'] \
  [--fail-reason "unresolved cause"] [--fix-owner <rule>]
```

`out/` delivers the netlist, matching nonempty SDC/SDF and any supporting files they require.
Consumers track this complete directory. Keep reports and explanatory evidence outside `out/`;
changes to the package require reassessment, not necessarily new computation. Use `--fail-reason` for invalid or incomplete work even when numbers
exist. Name the repair owner from the defect, including this stage for its own work. Acceptance
changes follow the user's actual authorization.

Finalize withdraws the previous result before judging. Exit 0 means a pass/fail result was written;
return `STATUS: DONE`. A nonzero exit means no result was produced; resolve the cause or return
`STATUS: BLOCKED <cause>`. A failing requirement is a conclusion, not a tool execution failure.
