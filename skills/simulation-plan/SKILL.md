---
name: simulation-plan
description: Use when generating or evolving a module's verification strategy, testpoints, TB scaffold and power measurement plan; not for implementing the testbench or running a regression.
---

# Verification Planning

Plan how the task's required behavior and power questions will be verified. Expected behavior comes
from the original intent and resolved design choices. Implementation or diagnostic evidence can
explain a discrepancy; it does not redefine the requirement being checked.

Write under `{workdir}`. Read `dispatch.json` for the input locations: `intent` is the original
material; `design`, `manifest`, `clocks`, `requirements`, `check_hints` and `top_io` resolve to the
specification directory. Use `design.md` for behavior, interfaces and timing scenarios, and consult
the original intent when its meaning or a derived requirement is in doubt.

## Author or amend the plan

Continue from the artifacts already in `{workdir}`. Use changed inputs (`scope`), reported failures
(`caused_by`) and any supplied decisions (`reasons`) to determine the work. Their absence does not
mean a first delivery. Preserve unaffected content and identifiers; create missing artifacts as
needed. A diagnosis supplies evidence to examine, not an automatic instruction to change acceptance.

| Artifact | Purpose |
|---|---|
| `verification-plan.md` | Strategy, power measurement meaning and material decisions; use [the outline](references/verification-plan-template.md) |
| `tb-scaffold.json` | Functional agents, tests, testpoints, reference-model/scoreboard organization and skipped checks |
| `sequences.json` | Functional sequences implemented by simulation |
| `power-scenarios.json` | Identifiers for the power measurements explained in the plan |

The sidecar formats are [tb-scaffold.schema.json](references/tb-scaffold.schema.json),
[sequences.schema.json](references/sequences.schema.json) and
[power-scenarios.schema.json](references/power-scenarios.schema.json).
[spec-input-contract.md](references/spec-input-contract.md) explains how the specification feeds
the functional scaffold and sequence reuse.

Account for each `check-hints.json` check in `testpoints[].covers[]` or a justified `skipped_checks[]`
entry. Assess disputed expectations and reachability against the original requirement and technical
evidence. Correct mistaken testpoints and report implementation defects to their owner. Record
material scope decisions in the plan.

Use [power-scenarios-template.md](references/power-scenarios-template.md) for task-relevant power
planning. Keep measurement meaning in verification-plan.md and identifiers in power-scenarios.json;
power-analysis implements the experiment.

## Check and review

`<skill>` is this skill's directory. Check the functional boundary and sidecars:

```bash
python3 <skill>/scripts/simplan/__main__.py materialize-scaffold --plan {workdir} --spec <design>
python3 <skill>/scripts/simplan/__main__.py check-scaffold --plan {workdir} --spec <design>
```

Repair local defects and recheck affected work. Have a reviewer assess the plan using
[plan-review-task-contract.md](references/plan-review-task-contract.md), providing the plan and
relevant input paths. Collect its findings before closing; report an incomplete review as unresolved.

Evaluate findings against the task and repair the plan where warranted. Recheck edits and have
substantive review findings reassessed. Decisions about intent follow the actual authorization:
act within an existing delegation, otherwise obtain the needed human decision. Record material
accepted findings in `plan-review/decisions.md`, identifying the decision and its authorization;
do not present an agent decision as the user's words. Present the plan and review paths with any
decision the user still needs to make.

## Close the stage

Finalize after completing this stage's work or when an unresolved issue must return to the caller:

```bash
python3 <skill>/scripts/simplan/__main__.py finalize \
  --workdir {workdir} --spec <design> \
  [--fail-reason "<unresolved cause>"] [--fix-owner <rule>] \
  [--revision '<scope of the amendment>']
```

Finalize checks the sidecars again and writes `result.json`; it does not judge the review prose.
Use `--fail-reason` for an unresolved blocking finding or incomplete review. Name the actual repair
owner: simulation-plan for this plan, specification for an upstream definition, or leave it unresolved
when the evidence does not identify one.

Exit 0 means the result was written, pass or fail; return `STATUS: DONE` and let the caller route it.
Exit 2 means closure failed; resolve the reported cause or return `STATUS: BLOCKED <cause>`.
