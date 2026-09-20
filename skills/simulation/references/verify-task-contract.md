# Run and assess verification

Read the assigned work scope, plan/testpoints, requirements, current TB and earlier results in
`{workdir}`. Compile changed sources (`make simv`), run the required regression (`make regress`)
and obtain the summary (`make summary`),
using existing valid evidence where the task permits. Wait for tools to finish and inspect failed
or missing tests; do not infer a cause from a missing status alone.

Investigate coverage using [coverage-iteration.md](coverage-iteration.md). Compare the actual DUT
instance subtree with the required bounds. Diagnose missed behavior from RTL, stimuli, checks and
reports rather than treating absence from the testpoint list as an intent defect.

Repair within the assigned scope and rerun affected checks. Changes to check meaning need the
stage owner's assessment and independent review. Shared plan or RTL defects are reported with
supporting evidence to their owner; do not edit upstream artifacts. Keep raw reports and any focused
experiment used to support a diagnosis. Do not change acceptance to make a result pass.

Return log/report paths and the outcome of the assigned work. For an unresolved regression failure,
identify the failing tests and their log locations. Coverage gaps can be described in the failure reason and referenced
reports; their presence in a testpoint list does not determine repair ownership.

Return `STATUS: DONE` when this work is complete, including an assessed failure; otherwise return
`STATUS: BLOCKED <cause>`. The stage owner handles repair, attribution and final closure. Do not
invoke kernel state transitions or dispatch further work.
