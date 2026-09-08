# Check hints

Read `{workdir}/requirements.json`, `{workdir}/top-io.json` and `{workdir}/interconnects.json`.
A row that points at a file under `<intent>/` is read there.
Write `{workdir}/check-hints.json` per `check-hints.schema.json`.

For every row judged `simulation` without a `target`, say how simulation observes it and against
what rule. Rows with any other judge get no hint; they are established elsewhere, and a hint
would turn them into gating checks the engineer did not ask for.

Observe at the top boundary. Name a cut-edge wire only when no top-boundary stimulus and
observation can tell the row holding from failing, and say why in that hint's `reference_rule` —
the reader who has to trust the exception is looking at the hint, not elsewhere.

End with `STATUS: DONE` and the path, or `STATUS: BLOCKED <reason>`.
