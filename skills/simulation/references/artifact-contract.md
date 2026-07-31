# `simulation` stage artifact contract

You run as a thin orchestrator over three sequential sub-Tasks
(`env-task-contract.md` → smoke gate → `conformance-review-task-contract.md` (Step 4) →
`verify-task-contract.md`); all share one stage `{workdir}`.
The artifacts below are split by which phase **owns** (writes) them. `result.json` is assembled by
the orchestrator, never by a sub-Task.

## Inputs (read)

- `Verification/simulation-plan/verification-plan.md`
- `Verification/simulation-plan/tb-scaffold.json` and `sequences.json` (**read-only** — basis for Rule A/B; the
  env phase materializes `agents` / `sequences` / `tests` / `testpoints`; the `power_scenarios[]`
  field coexists but is not consumed here — it is read by power-analysis)
- `Verification/simulation-plan/result.json` (gate)
- `Design/rtl-design/result.json` (gate + RTL filelist source)
- `${CLAUDE_SKILL_DIR}/defaults.yaml` (thresholds; bundled with the simulation skill)

## Outputs (write) — split by owning phase

All paths are relative to `{workdir}` (the only write root permitted for this run; both sub-Tasks
share it).

### env phase (wave 1 — `env-task-contract.md`)

| Artifact | Path (relative to `{workdir}`) | Description |
|------|------|------|
| `Makefile` | `Makefile` | Compile / regression entry point. |
| `env.sh` | `env.sh` | Environment variables. |
| `filelist.f` / `rtl_filelist.f` | same | Filelists. |
| `tb/uvm/**` | same | UVM code (driver / monitor / checker / RM / sequences / top; bound by Rule A). |
| `scripts/**` | same | Regression helper scripts. |
| `tests/testlist.json` | same | Testcase list (the verify phase may **append** stimulus-iterate entries). |
| `regression-log.txt` | same | `make smoke` writes the smoke-suite `RESULT` lines, which the smoke gate reads. `make regress` rewrites the file in the verify phase. |
| `logs/<test>.status` | same | Per-test `PASS`/`FAIL` status file written by each smoke `simv` run (the smoke gate reads these). |
| `verify-handoff.json` | same | Per-testpoint check-intent digest handed to the verify phase (schema in `env-task-contract.md`). Promoted artifact; written fresh by env-build every round. |

### conformance review phase (wave 2, Step 4 — `conformance-review-task-contract.md`)

| Artifact | Path (relative to `{workdir}`) | Description |
|------|------|------|
| `conformance-review.md` | `conformance-review.md` | Per-testpoint check-adequacy findings, written by the reviewer Task: prose per finding, `BLOCKING` on the heading of one that stops the round. The main thread gates on that marker and copies nothing out. Promoted artifact, and the record simulation-triage opens on a conformance fail. |

### verify phase (wave 3 — `verify-task-contract.md`)

| Artifact | Path (relative to `{workdir}`) | Description |
|------|------|------|
| `regression-log.txt` | same | `make regress` rewrites the file with the full-regress `RESULT` lines. |
| `structural-coverage.json` | same | Urg-derived structural coverage (`aggregate` dims `line`/`cond`/`fsm`/`toggle` + `per_module`); this is the gate source read by `sim finalize`. |
| `case-results.json` | same | The suite counts (`total_tests` / `passed_tests` / `failed_tests` / `not_run_tests` + the two percentages), derived by `write_summary.py` from `regression-log.txt` ∪ `testlist.json`. The structured home: `sim finalize` reads its counts from here, never from the two rendered views below. |
| `coverage-summary.txt` | same | A rendered view of `case-results.json` for a human (not the coverage gate source — that is `structural-coverage.json` + `sim finalize`). |
| `case-results-summary.md` | same | Review summary. |
| `<test_id>.fsdb` | run-dir root (NOT `logs/`) | Full-hierarchy FSDB waveform of a **failing** test's run (`-ucli` `$fsdbDumpvars`), for `simulation-triage` L1 waveform query. Per-run, large, **not promoted** (triage reads it via `sim_run`); gc-on-pass deletes it for passing tests, so only failing tests retain one. |

### orchestrator (finalize)

| Artifact | Path (relative to `{workdir}`) | Description |
|------|------|------|
| `result.json` | `result.json` | Stage envelope. Assembled by the orchestrator from the verify child's verdict + the smoke-gate result + `sim finalize`'s stdout verdict. |

> Note: `tests/testlist.json` is the one artifact written by env (initial materialization) and
> appended by verify (stimulus iterate) — its final form spans both phases.
>
> Note: `regression-log.txt` is written twice, not accumulated. `make smoke` writes the smoke
> `RESULT` lines the main-thread smoke gate reads (alongside `logs/<test>.status`, which do
> persist), and `make regress` then rewrites the file with the full-regress lines.

## `result.json` example (pass, full closed loop)

```json
{
  "stage": "simulation",
  "module": "<M>",
  "produced_at": "<ISO8601>",
  "status": "pass",
  "artifacts": [
    {"path": "Makefile"},
    {"path": "env.sh"},
    {"path": "filelist.f"},
    {"path": "rtl_filelist.f"},
    {"path": "tb/uvm"},
    {"path": "scripts"},
    {"path": "tests/testlist.json"},
    {"path": "regression-log.txt"},
    {"path": "logs"},
    {"path": "verify-handoff.json"},
    {"path": "conformance-review.md"},
    {"path": "structural-coverage.json"},
    {"path": "case-results.json"},
    {"path": "coverage-summary.txt"},
    {"path": "case-results-summary.md"}
  ],
  "stage_specific": {
    "total_cases": 20, "passed": 20, "failed": 0,
    "stimulus_iterations": 0,
    "coverage_summary": {
      "line": 92, "cond": 71, "fsm": 64, "toggle": 88
    }
  }
}
```

> `finalize` enumerates this list itself, in this order, keeping the entries whose path exists.
> Only what it lists is promoted to canonical, so a product missing here is a product the next
> stage cannot read even though the run passed.

## Cross-round carry

Your previous round's canonical output is already in `{workdir}` when you are dispatched, all of it
except `conformance-review.md`, which is re-derived every round. `rtl_filelist.f` arrives with the
rest and `bootstrap` then overwrites it against the current RTL; every other carried file survives,
because `bootstrap` writes only where a file is missing. On a first run nothing is carried and
`bootstrap` deploys the complete template.

## Forbidden outputs

- Do not write `verification-plan.md` / the plan sidecars (plan is a read-only external
  reference).
- Do not modify any file under `Design/rtl-design/`.
