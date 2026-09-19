# Check-adequacy review

Independently review the TB's checks, drivers, observations and initialization against the testpoints,
applicable requirements and original intent. Read the plan, check hints, reference sources and
relevant implementation evidence. Do not modify the TB or dispatch further work.

For each testpoint, determine whether its check can detect a violation of the intended behavior.
Check both the prediction and the stimulus/observation path. Use numerical, transaction or cycle
accuracy as the requirement demands; an expected value must have an independent basis. Confirm
that a detected mismatch causes a failed test, not just an informational message.

The materialization gate checks files and placeholders, and other stages perform their own tool
analyses. Those responsibilities do not make a concrete defect you discover unreportable. Explain
its effect and likely owner without pretending to have performed an unrelated analysis.

Write `{workdir}/check-review.md`. Each finding names the testpoint, source location, requirement,
evidence and acceptance impact. An unresolved defect that would let incorrect behavior pass is
blocking. Preferences and unmeasured risks should be distinguished from demonstrated violations.
A supplied diagnosis or earlier label does not replace this assessment.

The existing finalizer recognizes a `##` finding heading ending in `BLOCKING`; retain that marker
while the finding is unresolved. The rest of the report is ordinary prose. The stage owner reads
all findings and may challenge their basis. Reassess a repair or challenge against evidence and
record why a finding is resolved; do not merely remove its marker to permit closure.

Return `STATUS: DONE` with the report path when the review is complete, including when it found
problems. Otherwise return `STATUS: BLOCKED <cause>`; an absent or incomplete review is not clean.
