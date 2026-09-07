# The requirements ledger

Read `<intent>/brainstorm.md`, all of it, in whatever shape the engineer wrote it. The intent is
a tree: a file elsewhere under `<intent>/` that the document names as authoritative — a reference
model, a register map, a standard — is part of the intent, and whoever judges a row that points at
it reads it there. Write `{workdir}/requirements.json` per `requirements.schema.json`.

This is transcription, not classification. Walk the document top to bottom, one row per atomic
proposition the engineer states, about the design, about you as its implementer, or about the
context it lives in, in the engineer's own words.
Delegations, out-of-scope statements, pointers to external authorities, process requirements,
acceptance tests you will never see, and restatements are rows too; nothing is skipped because no
stage seems to want it.

`judge` is who establishes the row; the schema says what each value means. When you cannot
decide, write `unassignable` and the reason in `note` rather than guessing. `target` only when
the engineer's number is already in a unit a stage's tool reports.

End with `STATUS: DONE` and the path, or `STATUS: BLOCKED <reason>`.
