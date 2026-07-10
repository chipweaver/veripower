# verify sub-Task contract (wave 3)

The simulation main thread dispatches the **verify** child as the third sequential wave, only after
the smoke gate passes and the conformance gate clears. Your job: full regression, coverage iteration (Rule B), and the
review summary.

## Inputs (paths only — the main thread does not read these bodies)

- `{workdir}` — the **same** shared workdir the env-build child wrote in wave 1. It already holds the
  built TB (`tb/uvm/**`), the compiled `simv`, the env-phase artifacts, and
  `{workdir}/verify-handoff.json`.
- scaffold-specification testpoints path: `Verification/simulation-plan/scaffold-specification.json` —
  read `testpoints[].bins[]` for coverage-gap classification (Rule B) and `testpoints[].id` to
  cross-reference `verify-handoff.json`. (`agents` / `sequences` / `tests` are already materialized;
  do not re-materialize.)
- `{module}` — module name.

Use `{workdir}/verify-handoff.json` for check-intent (per-testpoint `asserts` + `seqs→bins`) rather
than re-reading the whole TB: it maps each uncovered coverage bin back to the sequence whose stimulus
to iterate (Rule B coverage-bin adjudication). On a regress failure you only route out
with `failing_cases` (no repair, no per-case check-mapping needed), so the handoff is not relied on
there.

## Work

1. **Regression**: `make regress`.
2. **Coverage iteration** (Rule B, see `coverage-iteration.md`): read `structural-coverage.json`
   (urg-derived structural dims `line`/`cond`/`fsm`/`toggle` from the `aggregate` block) and compare
   against `defaults.yaml.coverage_thresholds`:
   - All dimensions meet threshold → go to summary.
   - All uncovered bins map to `scaffold-specification.json.testpoints[].bins[]` → stimulus iterate
     (add seeds / sequences / constraint parameters), round budget at
     `defaults.yaml.stimulus_iterate_max_rounds`; each round re-runs `make regress`.
   - Any uncovered bin **not** inside scaffold testpoints → route out: write `failure_phase=coverage`
     + `gaps_not_in_testpoints` into the result fields (Rule B intent gap; mixed gaps take the intent
     fail first; stimulus iterate does not consume budget).
   - Iterate budget exhausted with stimulus-layer gaps remaining → route out: `failure_phase=coverage`
     + `gaps_in_testpoints`.
3. **Summary**: `make summary` produces `coverage-summary.txt` + `case-results-summary.md`. (The full exit self-check —
   `sim finalize`, thin-D1 + D5/D6 — runs at orchestrator finalize, not here.)

## Authority

- **Rule B stimulus iterate only**: seed / tighten existing seq constraint params / testlist append.
- **regress failure → route out** (do not repair here). A regression failure — whether
  scaffold/wiring OR checker/RM semantic — is **not** repaired in this wave: write `failure_phase=regress` + `failing_cases` and let the orchestrator / caller decide. There is **no
  regress-time scaffold/checker/RM repair** (that authority belonged to the env wave's Rule A budget,
  which closed when smoke passed).

## Write-domain

Writes are confined to `tb/uvm/seq/*` + `tests/testlist.json` (Rule B). This is **not**
pure append-only: Rule B may tune the constraint params of an **existing** seq, and testlist entries
are appended (do not change the semantics of existing testlist entries). The env child's checker / RM
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
- End the response with `STATUS: DONE` + a single JSON line carrying the result `stage_specific`
  fields the orchestrator folds into `result.json` — on a pass run, the informational counts; on a
  route-out, the failure fields:

  ```json
  {"failure_phase": "coverage", "coverage_gaps": ["..."], "gaps_not_in_testpoints": ["..."]}
  ```

  (omit the failure fields on a clean pass; emit `stimulus_iterations` / coverage summary counts
  instead) — or `STATUS: BLOCKED <one-line reason>` on a program exception. `STATUS: BLOCKED` is a
  **harness-level** signal, distinct from the `result.json.status` enum (`pass`/`fail` only); the
  orchestrator maps it to `status=fail` + `fail_reason`.
