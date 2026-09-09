# Review

Read `<intent>/brainstorm.md` and every artifact in `{workdir}` — whatever is there this round, plus
`spec-review/decisions.md` when it exists, which is the user's rulings from an earlier round and why
a row may say something the brainstorm does not. Open a file beside the brainstorm when a check
needs it: a port list the rows say is in an interface document is checked against that document.
You are a fresh reader; trust none of them because they were written.

No two of them may contradict each other, and none may contradict the brainstorm. Write
`{workdir}/spec-review/findings/<name>.md`, the name the caller gave you, prose, one section per
finding, saying what you compared against each time.

Two directions are yours alone, because nothing else holds both sides:

- A row judged `specification` is made true by something inside this stage's own artifacts.
  Point at it. Report a row you cannot point at, and a sidecar entry no row supports.
- A check hint's rule must establish the rows it names and assert nothing they do not. A rule is
  an obligation, and one no row carries is an obligation nobody asked for. A hint observing
  something other than the top boundary says why in its own `reference_rule`; report one that
  does not.

End with `STATUS: DONE` and the path, or `STATUS: BLOCKED <reason>`.
