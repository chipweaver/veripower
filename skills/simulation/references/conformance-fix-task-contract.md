# Conformance-fix sub-Task contract

Dispatched on every conformance trip. Do not call the Task tool and do not call `kernel.py`: the
parent session owns state transitions.

**Job:** make the flagged checks verify what their testpoints set out to verify. The findings
marked `BLOCKING` in `{workdir}/conformance-review.md` are your scope, and `{workdir}` is your
whole write domain — the plan and the check hints are the statement you are being measured
against, and they are handed to you as reference.

## Output

- Fixed: `STATUS: DONE`. The reviewer re-runs over your work. There is no round cap.
- The defect is in the plan or the testpoint intent, not in the check:
  `STATUS: BLOCKED <tp_id: what the plan would have to say instead>`. The stage fails out on this
  and routes upstream. You are the one who decides this — the reviewer read the checks, you are
  the one who tried.
