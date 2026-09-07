# Requirements review

Read `<intent>/brainstorm.md`, `{workdir}/requirements.json`, `{workdir}/design.md` and the
three sidecars `clocks.json`, `top-io.json`, `interconnects.json`. Open a file beside the
brainstorm when a check needs it: a port list the rows say is in an interface document is checked
against that document. You are a fresh reader; trust none of them because they were written.

Write `{workdir}/spec-review/requirements.md`, prose, one section per finding: a proposition in
the brainstorm no row carries; a row whose `verbatim` the brainstorm does not contain; a sidecar
entry no row supports; a place where `design.md` contradicts a row or restates one instead of
citing it. Say what you compared against each time. Found nothing in a category, say so.

End with `STATUS: DONE` and the path, or `STATUS: BLOCKED <reason>`.
