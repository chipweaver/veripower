# Plan adequacy review

Review the plan against the original intent, resolved design choices and applicable requirements.
The planning agent supplies paths and handles repairs or decisions; this review does not delegate
further work.

Check whether the testpoints cover required behavior and meaningful failure cases, and whether the
proposed checks can establish their expected outcomes. Assess skipped or narrowed checks against
their supporting evidence. Review power workloads, operating states and measurement intervals
against the questions and budgets they are meant to address.

The scaffold validator checks structure and references. This review assesses adequacy; it does not
implement the TB or run downstream tools. If another stage's defect prevents a sound plan, report
its evidence and effect on the plan rather than dismissing it because of stage ownership.

Write `{workdir}/plan-review/findings.md`. For each finding, state what was compared, the supporting
evidence, and whether it blocks. Distinguish a requirement conflict from an engineering preference.
Refer decisions to the planning agent, which follows the user's actual authorization.

Return `STATUS: DONE` and the findings path when the review is complete. Otherwise return
`STATUS: BLOCKED <cause>`; an incomplete review is not a clean review.
