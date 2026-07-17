# Conformance-fix sub-Task contract (self-heal; dispatched by Step 4 on a self-locus conformance trip)

The simulation main thread dispatches this Level-1 `Task(run_in_background=True)` when the Step-4
conformance gate trips with self-locus findings. Do not call the Task tool (no Level-2 dispatch).

**Job:** Fix the self-locus check defects the conformance gate flagged (`category ∈ {missing,
wrong-behavior, fake-green}`) so the TB checks adequately cover the testpoint intent. You change
**only the check implementation** — never the source of the expected behavior.

## Inputs (paths only — the main thread does not read these bodies)

- `{workdir}` — already populated with `tb/uvm/**`.
- `conformance-review.json` — the flagged findings, each carrying its `tp_id` / `category` / `location`.
- The scaffold-spec `testpoints[].inlined_check_hints[]` (the check-intent source) — **read-only**.
- `verification-plan.md` §3 (the intent source) — **read-only**.

## May change

- The checker / scoreboard / assertion / monitor check logic under `tb/uvm/**` — strengthen or
  correct the check for each flagged finding.

## Must NOT change (Iron Rule boundary)

- `verification-plan.md` / `scaffold-specification.json` (the intent source, read-only upstream).
  Never loosen a check to make the gate pass falsely.

## Direction

A flagged finding means the check is too weak, missing, or fake-green. Every fix **tightens** — add
the missing check, correct the wrong check, remove the fake-green — never relax.

## Exit (return STATUS)

- Fixed → `STATUS: DONE`.
- You judge a flagged finding is actually a plan/intent error or needs upstream (beyond what a check
  implementation can fix) → `STATUS: BLOCKED <tp_id: needs upstream/plan>`. Do not count rounds.
