# Specification review

Read the original intent, the artifacts being delivered and any recorded decisions. Consult the
referenced source documents when needed. Compare the ledger, design choices, boundary, check hints
and constraints in both directions: required behavior must be accounted for, and added obligations
need a basis in the task or an authorized decision.

For a row judged by specification, identify the artifact that establishes it. Check that the hints
collectively establish the simulation obligations they name, including conditions and exceptions.
A proposed implementation, existing artifact or earlier decision is not proof of a technical claim.
In particular, authorization to change acceptance does not establish unreachability or erase
contrary measurements.

Write `{workdir}/spec-review/findings/<name>.md`, using the name supplied by the stage owner.
State each finding's evidence, requirement and acceptance impact. Separate factual errors, missing
evidence and choices requiring a decision. Report relevant contradictions even if another stage
must repair them. Reassess repairs and challenges on their evidence.

Do not edit reviewed artifacts or dispatch further work. Return `STATUS: DONE` and the findings
path when the review is complete; otherwise return `STATUS: BLOCKED <cause>`. A completed review
can contain blocking findings.
