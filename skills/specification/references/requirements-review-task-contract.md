# Requirements review

Read `<intent>/brainstorm.md`, `{workdir}/requirements.json`, `{workdir}/design.md`, the four
sidecars `manifest.json`, `clocks.json`, `top-io.json`, `interconnects.json`, and `{workdir}/spec-review/decisions.md`
when it exists — the user's rulings from an earlier round, which is why a row may say something
the brainstorm does not. Open a file beside the brainstorm when a check needs it: a port list the
rows say is in an interface document is checked against that document. You are a fresh reader;
trust none of them because they were written.

No two of these may contradict each other, and none may contradict the brainstorm. Write
`{workdir}/spec-review/findings/requirements.md`, prose, one section per finding, saying what you
compared against each time.

One direction is yours alone: a row judged `specification` is established by a sidecar entry — a
clock, a port, a cut edge, the top module's name, an SDC statement. Report a row nothing
realizes, and a sidecar entry no row supports.

End with `STATUS: DONE` and the path, or `STATUS: BLOCKED <reason>`.
