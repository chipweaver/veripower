---
name: rtl-design
description: Use when writing or modifying RTL and its file/constraint annotations, reviewing implementation against requirements, or repairing an implementation defect; not for running synthesis or functional regression as a pipeline stage.
---

# RTL Design

Implement the required behavior and boundary, and resolve findings before delivering the RTL.
Read `{workdir}/dispatch.json` for the input locations. `design.md` proposes an architecture;
`requirements.json`, the original `intent`, `top-io.json` and `clocks.json` establish the applicable
requirements and boundary. Read the sources needed to assess a discrepancy. Upstream artifacts
are read-only; write this stage's work under `{workdir}`.

## Implement and review

Choose the module split to suit the task. Continue from carried RTL and use changed inputs,
reported failures and decisions in `dispatch.json` to scope repairs. Preserve unaffected work.
Implement directly or delegate cohesive parts using [child-task-contract.md](references/child-task-contract.md).
Coordinate shared interfaces and avoid concurrent edits to the same files.

Deliver `src/`, `rtl-files.json` and `constraint-annotations.json`. Their formats are in the matching
reference schemas. Include every implemented child and the source/include order needed to compile
it. Compile the complete file set before closure.

Have an independent reviewer assess the delivered RTL using
[rtl-review-task-contract.md](references/rtl-review-task-contract.md). Read the findings and their
supporting evidence. Resolve disagreements against the requirement, implementation and measurements;
request focused reassessment when evidence changes and retain the reviewer's findings.

Assess findings by their acceptance impact, including those labeled non-blocking. Repair demonstrated
violations here or return them to their owner; identify evidence needed to assess unmeasured risks.

Use targeted checks to validate repairs and consider affected integration behavior. Changes to
acceptance meaning require the user's actual authorization. An authorized change establishes a
new scope; it does not prove a previously unsupported technical claim.

## Close

Close when this stage's work is complete or an unresolved issue must return to the caller:

```bash
python3 <skill>/scripts/rtl/__main__.py finalize --workdir {workdir} \
  [--fail-reason "<unresolved violation or incomplete work>"] [--fix-owner <rule>]
```

`<skill>` is this skill's directory. Finalize validates the file/annotation sidecars and source
presence. It cannot establish semantic correctness from those files. Supply `--fail-reason` for an
unresolved requirement violation, incomplete review or failed validation, even if the RTL compiles.
`stage_specific.fail_reason` carries that cause. Name the actual repair owner; local repair is
`rtl-design`. Leave ownership unresolved when the evidence does not identify it.

Exit 0 means `result.json` was written, pass or fail; return `STATUS: DONE` and let the caller route
it. Exit 2 means closure failed; resolve the reported cause or return `STATUS: BLOCKED <cause>`.
