# Conformance-fix sub-Task contract (dispatched when the conformance gate trips)

The simulation main thread dispatches this Level-1 `Task(run_in_background=True)` on every
conformance trip. Do not call the Task tool (no Level-2 dispatch) and do not call `kernel.py`: the
parent session owns state transitions.

**Job:** make the flagged checks verify what their testpoints set out to verify. You change **only
the check implementation**, never the source of the expected behavior.

**And you are the one who decides whether that is possible.** The reviewer read the checks; you are
the one who tries to fix them. If a finding turns out to be a defect in the plan rather than in the
check, say so and stop, and the stage routes it upstream on your word. Nobody asked the reviewer to
guess this in advance, because guessing it is worth less than trying.

## Inputs (paths only — the main thread does not read these bodies)

- `{workdir}` — already populated with `tb/uvm/**`.
- `conformance-review.md` — the findings. The ones marked `BLOCKING` are your scope.
- The scaffold-spec `testpoints[].inlined_check_hints[]` (the check-intent source) — **read-only**.
- `tb-scaffold.json`'s `testpoints[].intent` (the intent source) — **read-only**.

## May change

- The checker / scoreboard / assertion / monitor check logic under `tb/uvm/**` — strengthen or
  correct the check for each flagged finding.

## Must NOT change (Iron Rule boundary)

- `verification-plan.md` / the plan sidecars (the intent source, read-only upstream).
  Never loosen a check to make the gate pass falsely.

## Direction

A flagged finding means the check is missing, too weak, or green for the wrong reason. Every fix
tightens: add the missing check, correct the wrong one, remove whatever was making it pass. Never
relax one to clear the gate; the reviewer runs again on what you leave, and a check loosened here is
a testpoint that verifies nothing for the rest of the module's life.

## Output

- Fixed: `STATUS: DONE`. The reviewer re-runs over your work.
- The defect is in the plan or the testpoint intent, not in the check:
  `STATUS: BLOCKED <tp_id: what the plan would have to say instead>`. The stage fails out on this
  and routes upstream. Do not count rounds.
