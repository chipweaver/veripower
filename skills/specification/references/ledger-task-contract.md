# Requirements ledger

Read the complete delivered intent and the named authorities needed to interpret it. Write
`{workdir}/requirements.json` using [requirements.schema.json](requirements.schema.json).
Account for requirements, scope, authorization, external responsibilities and decisions needed
to proceed, including obligations this pipeline cannot establish.

Organize entries by the conclusions they need. Repeated statements may share an entry when their
meaning, conditions, scope and judge agree; retain source references and added qualifications in
`note`. Keep independently judged obligations separate; give each automatic numerical bound its own
target entry. Granularity should make each entry fully judgeable, rather than mirror every
occurrence in the document.

`verbatim` quotes the relevant original wording, including labels and context needed to preserve
meaning. Use `note` to explain the entry's scope, source locations, interpretations or decisions;
keep these distinct from the user's words. Consult the source when an entry cannot be understood
on its own. Preserve IDs for unchanged obligations and update affected references when revising.

Assign `judge` by who can establish the obligation with evidence. Stages can judge reports and
other evidence without an automatic parser; `outside` identifies work not established by this
workflow, with its responsibility made explicit. A numerical `target` is closed by the stage's
computed comparison and covers only that quantity and measurement scope. Other independent
obligations need their own judgment; a note cannot extend what the numeric verdict establishes.

Distinguish missing intent or necessary authority from tools, artifacts and decisions the task
asks its implementer to prepare. Assign that work to its responsible stage. When the basis for
an obligation remains unresolved, identify the concrete missing definition or evidence in `note`
and use the appropriate judge from the schema. Resolve decisions under the actual authorization;
do not invent acceptance conditions or replace missing authority with a convenient assumption.

Check both directions against the original intent: every obligation and material qualification
is accounted for, and every claimed obligation has a source or an authorized decision. Return
`STATUS: DONE` with the output path, or `STATUS: BLOCKED <cause>` if the work is incomplete.
