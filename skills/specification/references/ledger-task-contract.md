# The requirements ledger

Read `<intent>/brainstorm.md`, all of it, in whatever shape the engineer wrote it. The intent is
a tree: a file elsewhere under `<intent>/` that the document names as authoritative — a reference
model, a register map, a standard — is part of the intent, and whoever judges a row that points at
it reads it there. Write `{workdir}/requirements.json` per `requirements.schema.json`.

This is transcription, not classification. Walk the document top to bottom and account for every
place it makes a claim or leaves a hole. A claim is a row in the engineer's own words, about the
design, about you as its implementer, or about the context it lives in. A hole — a blank cell, a
bound the prose never gives, a behaviour it names and never defines — is a row too: `judge:
human`, the surrounding sentence as `verbatim`, what is missing in `note`. Left out, a hole
reaches every later reader as a settled question.
Delegations, out-of-scope statements, pointers to external authorities, process requirements,
acceptance tests you will never see, and restatements are rows too; nothing is skipped because no
stage seems to want it.

`judge` and `target` each hold one value, so a sentence two stages establish, or one bounding two
dimensions, becomes one row per judge or per bound — each keeping the engineer's sentence as its
`verbatim`, with `note` saying why it split. Rewriting the sentence to fit one row destroys the
only wording every later reader is held to.

`verbatim` is a contiguous span of the document, so any reader can find it there. A cell or a
bullet that means nothing alone takes the span that gives it meaning — the label above its list,
the row it sits in — never one assembled from pieces the document does not put together.

`judge` is who establishes the row; the schema says what each value means. Write `unassignable`
with the reason in `note` when you cannot decide — including when the row rests on an authority
that is not in the container, since nobody downstream can establish it either. `target` only when
the engineer's number is already in a unit a stage's tool reports.

End with `STATUS: DONE` and the path, or `STATUS: BLOCKED <reason>`.
