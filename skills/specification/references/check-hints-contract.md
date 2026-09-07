# Check hints for your child

Read `{workdir}/requirements.json`, your child's `rtl_modules` from `manifest.json`, and the wire list
`derive-ports` gave you. A row that points at a file under `<intent>/` is read there.
Write `{workdir}/check-hints/<child>.json` per `check-hints.schema.json`.

For every row judged `simulation` without a `target` that your child's RTL realizes, say how
simulation observes it and against what rule. Rows with any other judge get no hint; they are
established elsewhere, and a hint would turn them into gating checks the engineer did not ask for.
Observe at the boundary; name an internal signal only when no boundary stimulus and observation
can tell the row holding from failing, and say why in your child design document. A row two children both
realize may appear in both files; a row no child covers is caught at the gate.

End with `STATUS: DONE` and the path, or `STATUS: BLOCKED <reason>`.
