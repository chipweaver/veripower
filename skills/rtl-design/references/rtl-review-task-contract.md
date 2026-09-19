# RTL intent review

Review the assigned RTL and its integration obligations against the applicable requirements,
original intent and design decisions. Read the implementation and any referenced algorithms or
interface definitions needed to establish the facts. Write under `{workdir}/semantic-review/`;
do not edit the implementation or dispatch further work.

Check required behavior, structure, interfaces and hard limits. A requirement assigned to this stage
remains binding regardless of a broad label such as area, timing or power. Report a concrete conflict
you discover even if another stage must fix it. Do not duplicate downstream tool runs without a
question they need to answer; distinguish a measured violation from an unmeasured risk.

For a whole-design limit, account for all contributing parts before claiming compliance. Explain
the measurement scope and any unresolved interpretation. Tools or focused experiments can support
the review; their inputs and results should be available to the stage owner.

Each finding should identify the requirement, evidence, effect on acceptance and likely repair
owner. A demonstrated violation or a defect in the evidence this stage claims prevents acceptance;
an analysis assigned to a later stage is still pending, not already failed or satisfied. Existing architecture notes
and earlier review labels are evidence to check, not reasons to dismiss a contradiction.

After a repair or a reasoned challenge, reassess the relevant finding against the changed evidence.
Preserve enough of its basis to show why it is resolved. Do not resolve it by relabeling the same
unmet requirement or by assuming another stage will catch it.

Return `STATUS: DONE` with the review paths when the assigned review is complete, including when
it found defects. If it could not be completed, return `STATUS: BLOCKED <cause>` and identify what
is missing. Completion of a review does not mean the reviewed RTL passes.
