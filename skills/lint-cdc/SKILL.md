---
name: lint-cdc
description: Check RTL lint and clock-domain crossings with SpyGlass, evaluate violations and justified waivers, and close the current assessment.
---

# Lint and CDC

Assess the RTL against the task's lint and CDC requirements. Read `dispatch.json`, original intent,
requirements, RTL, constraint annotations and specification SGDC. Use carried evidence when its
implementation, setup and scope still apply; choose the checks the current task needs.

Write under `{workdir}`; upstream inputs remain read-only. The framework carries published setup
and reports into this directory, without the old verdict. Keep useful analysis in `evidence/`.

## Prepare and check

`<skill>` is this skill's directory:

```bash
python3 <skill>/scripts/lintcdc/__main__.py bootstrap --workdir {workdir}
```

Bootstrap installs missing setup without overwriting authored files and refreshes the file list
and generated SGDC. `constraint-annotations.json`
supplies synchronizer, reset, case-analysis and quasi-static declarations. Check inherited
`scripts/local.sgdc` and `scripts/waiver.tcl` against the current design. Correct invalid input
declarations at their source.

Run `make lint`, `make cdc`, or `make all` from the prepared workdir; `all` shares elaboration.
The entrypoint withdraws the selected check's old summaries before execution. Wait for completion,
read the reports and inspect violations. A waiver needs a specific `-comment` explaining why it is
valid under the requirements; determine whether a warning limit applies before or after waivers.
Repair local setup errors and rerun the affected checks.

## Judge and close

```bash
python3 <skill>/scripts/lintcdc/__main__.py finalize --workdir {workdir} \
  [--requirements '[{"id":"R-1","met":true,"actual":"observed result","measured":"report and scope"}]'] \
  [--fail-reason "unresolved cause"] [--fix-owner <rule>]
```

Declare a judgment for every lint-cdc requirement using the reports and the actual waiver policy.
`finalize` reads `lint-violations.json` and `cdc-violations.json` and checks waiver reasoning.
Use `--fail-reason` for invalid or incomplete checks even if old reports contain numbers. Name
the repair owner from the defect, including this stage for its own setup; do not infer ownership
from the path of an error. [Attribution guidance](references/attribution-rules.md) describes the constraint sources to check.
Acceptance changes follow the user's actual authorization.

Finalize withdraws the previous result before judging. Exit 0 means a pass/fail result was written;
return `STATUS: DONE`. On a nonzero exit, resolve the cause or return `STATUS: BLOCKED <cause>`.
