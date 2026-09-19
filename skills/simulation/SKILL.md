---
name: simulation
description: Implement, review and run a module's functional testbench, diagnose verification failures and assess coverage; not for changing upstream RTL or requirements.
---

# Functional Simulation

Establish whether the implementation meets the applicable behavior and coverage requirements.
The stage owner assesses source, reports and review evidence to reach the conclusion. Implement
or delegate focused work; use an independent reviewer for check adequacy.

Read `{workdir}/dispatch.json` for the current inputs and work scope. `intent`, `requirements`,
`plan`, `scaffold`, `check_hints`, `spec` and `rtl` provide original requirements, verification
strategy, boundary and implementation. Write under `{workdir}`; upstream artifacts are read-only.
Use the original algorithm/specification as the reference. Inspecting RTL to diagnose a failure
must not turn the implementation into its own expected behavior.
See [artifacts.md](references/artifacts.md) for report locations and which diagnostic files are published or retained per run.

## Build and check

Continue from carried TB and results, changing what the current inputs or failures require.
Use [env-task-contract.md](references/env-task-contract.md) for setup and materialization details,
and [authoring-checks.md](references/authoring-checks.md) for check semantics. If delegating, supply
the relevant input paths and work scope; collect the actual results before acting on them.

Compile changed sources, run appropriate smoke checks and validate materialization. Missing test
results or a failed tool command require investigation; neither identifies the repair owner by
itself. Repair local faults and retry affected work. Return an upstream defect with evidence when
it cannot be repaired within this stage.

Have the TB reviewed using [check-review-task-contract.md](references/check-review-task-contract.md).
Assess all findings by their evidence and acceptance impact, including those labeled non-blocking.
Validate repairs and obtain independent reassessment of changed checks or disputed findings.
Retain the review record and report incomplete reviews or unresolved violations at closure.

## Verify and diagnose

Use [verify-task-contract.md](references/verify-task-contract.md) to run the required regression and
[coverage-iteration.md](references/coverage-iteration.md) to investigate coverage. Reuse applicable
existing evidence; do not repeat unrelated tool work. Before closure, the case results and coverage
must describe the tests and implementation being delivered, including any failed or unrun cases.

Read RTL, TB, reports and traces as needed. A focused experiment can distinguish missed stimulus,
an incorrect check, instrumentation, an implementation defect and a requirement ambiguity. A
behavior missing from the testpoint list does not determine which of these is responsible.

Use evidence to justify any measurement exclusion. An authorized acceptance change establishes a
new scope; it does not prove unreachable behavior or satisfy an unchanged original requirement.
Decisions follow the user's actual authorization, whether made by a person or under delegation.

## Close the stage

`<skill>` is this skill's directory. Close after the required work is complete or when an unresolved
issue must return to the caller. Use a failure result for a known violation or incomplete work:

```bash
python3 <skill>/scripts/sim/__main__.py finalize --workdir {workdir} \
  --phase fail --fail-reason "<unresolved cause and evidence>" [--fix-owner <rule>] \
  [--verify-verdict <case-failure-record.json>]
```

When the evidence supports acceptance, run the deterministic final checks:

```bash
python3 <skill>/scripts/sim/__main__.py finalize --workdir {workdir} --phase final \
  --plan <scaffold> --requirements <requirements>/requirements.json \
  --check-review {workdir}/check-review.md [--fix-owner <rule>]
```

Finalize checks materialization, unresolved `BLOCKING` review headings, bounded coverage and test
results. It cannot adjudicate prose: a known violation not marked by the reviewer still needs
`--phase fail --fail-reason`. Keep the evidence in the existing reports/review record.

Name the owner from the actual defect, not the filename or the failed step. Local TB repair is
`simulation`; an implementation defect is `rtl-design`; a wrong plan or requirement goes to its
producer. If ownership remains unresolved, omit it; the caller can dispatch simulation-triage.

Exit 0 means `result.json` was written, pass or fail. A nonzero exit means closure failed; fix the
reported cause or return it as unresolved. The caller decides what runs next from the result.
