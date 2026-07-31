# verify sub-Task contract (wave 3)

The simulation main thread dispatches the **verify** child as the third sequential wave, only after
the smoke gate passes and the conformance gate clears. Your job: full regression, coverage iteration (Rule B), and the
review summary.

## Inputs (paths only — the main thread does not read these bodies)

- `{workdir}` — the **same** shared workdir the env-build child wrote in wave 1. It already holds the
  built TB (`tb/uvm/**`), the compiled `simv`, the env-phase artifacts, and
  `{workdir}/verify-handoff.json`.
- testpoints path: `<scaffold>/tb-scaffold.json` —
  read `testpoints[].intent` and `bins[]` for coverage-gap classification (Rule B) and
  `testpoints[].id` to cross-reference `verify-handoff.json`. (`agents` / `sequences` / `tests` are
  already materialized; do not re-materialize.)
- `{module}` — module name.

Use `{workdir}/verify-handoff.json` for check-intent (per-testpoint `asserts` + `seqs→bins`) rather
than re-reading the whole TB: it maps each uncovered coverage bin back to the sequence whose stimulus
to iterate (Rule B coverage-bin adjudication). On a regress failure you only route out
with `failing_cases` (no repair, no per-case check-mapping needed), so the handoff is not relied on
there.

## Work

1. **Regression**: `make regress`.
2. **Coverage iteration** (Rule B, see `coverage-iteration.md`): compare
   `structural-coverage.json`'s `aggregate` dims (`line`/`cond`/`fsm`/`toggle`) against
   `defaults.yaml.coverage_thresholds`. Every dimension at or above threshold goes straight to
   summary. Otherwise take the named items from the same file's `uncovered[]`, classify each as a
   stimulus-layer or intent-layer gap per `coverage-iteration.md`, and either iterate stimulus
   within `defaults.yaml.stimulus_iterate_max_rounds` rounds or route out with
   `failure_phase=coverage`.
3. **Summary**: `make summary` produces `coverage-summary.txt` and `case-results-summary.md`.
   The exit gates run at the orchestrator's finalize, not here.

## Authority

- **Rule B stimulus iterate only**: seed / tighten existing seq constraint params / testlist append.
- **regress failure → route out** (do not repair here). A regression failure — whether
  scaffold/wiring OR checker/RM semantic — is **not** repaired in this wave: write `failure_phase=regress` + `failing_cases` and let the orchestrator / caller decide. There is **no
  regress-time scaffold/checker/RM repair** (that authority belonged to the env wave's Rule A budget,
  which closed when smoke passed).

## Write-domain

Writes are confined to `tb/uvm/seq/*` + `tests/testlist.json` (Rule B). This is **not**
pure append-only: Rule B may tune the constraint params of an **existing** seq, and testlist entries
are appended (do not change the semantics of existing testlist entries). An appended entry carries
the same six fields the scaffold emits — `test_id`, `uvm_testname`, `feature_id`, `feature_name`,
`suites`, `seqs` — copying `feature_id` / `feature_name` verbatim from the entry whose coverage gap
it is closing; `write_summary.py` reads all six unconditionally, so an entry missing one aborts the
summary. The env child's checker / RM
/ scaffold structure (driver / monitor / checker / refmodel / top / agent / env / test) is
**read-only reference** in this wave — do not edit it; a regress failure rooted there routes out
instead.

## Prohibitions

- **No Level-2 dispatch:** do not call the Task tool.
- **No `kernel.py`:** do not call `kernel.py` — the parent session owns state transitions.
- Stay inside `{workdir}`: all writes confined to the write-domain above. Do not modify the plan or
  RTL (RTL-class issues belong to the RTL editing stage; do not exceed your authority),
  and do not re-author the env child's scaffold / checker / RM.

## Red Flag

| Excuse | Reality |
|---|---|
| "Uncovered bins are outside the testpoints, but I'll iterate stimulus anyway and pass" | Bins outside scaffold testpoints are an intent issue → route out with `failure_phase=coverage` + `gaps_not_in_testpoints` (Rule B), not a stimulus problem. |

## Output

- Verify-phase artifacts written in `{workdir}`: `regression-log.txt`, `structural-coverage.json`,
  `coverage-summary.txt`, `case-results-summary.md` (artifact ownership split is in
  `artifact-contract.md`).
- End the response with `STATUS: DONE` plus a single JSON line. On a clean pass the only field
  read from it is `stimulus_iterations`, the number of Rule B rounds you spent; the suite counts
  and coverage numbers are read off `case-results.json` and `structural-coverage.json` by
  finalize, so do not restate them here. On a route-out, carry the failure fields:

  ```json
  {"failure_phase": "coverage", "coverage_gaps": ["..."], "gaps_not_in_testpoints": ["..."]}
  ```

  On a `regress` route-out each failing case is one `failing_cases[]` entry, and its shape is
  pinned by `references/result.schema.json`: `test_id` (how triage reaches
  `logs/<test_id>.log`) and `error_message` (its log anchor) are required, `log_snippet` is
  optional. A misspelled key fails the envelope rather than leaving triage with nothing to read.

  On a program exception, end with `STATUS: BLOCKED <one-line reason>` instead. That is a
  harness-level signal, distinct from `result.json`'s `status` enum (`pass`/`fail` only); the
  orchestrator maps it to `status=fail` plus a `fail_reason`.
