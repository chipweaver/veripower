# `simulation` stage artifact contract

You run as a thin orchestrator over three sequential sub-Tasks
(`env-task-contract.md` → smoke gate → `conformance-review-task-contract.md` (Step 4) →
`verify-task-contract.md`); all share one stage `{workdir}`.
The artifacts below are split by which phase **owns** (writes) them. `result.json` is assembled by
the orchestrator, never by a sub-Task.

## Inputs (read)

- `Verification/simulation-plan/verification-plan.md`
- `Verification/simulation-plan/scaffold-specification.json` (**read-only** — basis for Rule A/B; the
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
| `regression-log.txt` | same | `make smoke` writes the smoke-suite `RESULT` lines (the verify phase **appends** the full-regress `RESULT` lines). |
| `logs/<test>.status` | same | Per-test `PASS`/`FAIL` status file written by each smoke `simv` run (the smoke gate reads these). |
| `verify-handoff.json` | same | Per-testpoint check-intent digest handed to the verify phase (schema in `env-task-contract.md`). |

### conformance gate phase (wave 2, Step 4 — `conformance-review-task-contract.md`; main-thread aggregated)

| Artifact | Path (relative to `{workdir}`) | Description |
|------|------|------|
| `conformance-review.json` | `conformance-review.json` | Per-testpoint check-adequacy findings (schema `conformance-review.schema.json`). The main thread assembles it from the reviewer Task's JSON, schema-validates it, and gates on it. Promoted advisory artifact. |

### verify phase (wave 3 — `verify-task-contract.md`)

| Artifact | Path (relative to `{workdir}`) | Description |
|------|------|------|
| `regression-log.txt` | same | `make regress` **appends** the full-regress `RESULT` lines to the env-written log. |
| `structural-coverage.json` | same | Urg-derived structural coverage (`aggregate` dims `line`/`cond`/`fsm`/`toggle` + `per_module`); this is the gate source read by `sim finalize`. |
| `coverage-summary.txt` | same | Human-readable coverage summary (no longer the gate source; the gate source is `structural-coverage.json` + `sim finalize`). |
| `case-results-summary.md` | same | Review summary. |

### orchestrator (finalize)

| Artifact | Path (relative to `{workdir}`) | Description |
|------|------|------|
| `result.json` | `result.json` | Stage envelope. Assembled by the orchestrator from the verify child's verdict + the smoke-gate result + `sim finalize`'s stdout verdict. |

> Note: `tests/testlist.json` is the one artifact written by env (initial materialization) and
> appended by verify (stimulus iterate) — its final form spans both phases.
>
> Note: `regression-log.txt` is likewise dual-phase — env writes the smoke `RESULT` lines (the
> source the main-thread smoke gate reads, alongside `logs/<test>.status`); verify appends the
> full-regress `RESULT` lines. Its final form spans both phases.

## `result.json` example (pass, full closed loop)

```json
{
  "schema_version": 1,
  "stage": "simulation",
  "module": "<M>",
  "produced_at": "<ISO8601>",
  "status": "pass",
  "artifacts": [
    {"path": "Makefile",                 "kind": "make_entry"},
    {"path": "env.sh",                   "kind": "env"},
    {"path": "filelist.f",               "kind": "filelist"},
    {"path": "rtl_filelist.f",           "kind": "filelist"},
    {"path": "tb/uvm/",                  "kind": "uvm_tb"},
    {"path": "conformance-review.json",  "kind": "conformance_review"},
    {"path": "scripts/",                 "kind": "scripts"},
    {"path": "tests/testlist.json",      "kind": "testlist"},
    {"path": "regression-log.txt",       "kind": "regression_log"},
    {"path": "structural-coverage.json", "kind": "coverage"},
    {"path": "coverage-summary.txt",     "kind": "coverage_summary"},
    {"path": "case-results-summary.md",  "kind": "summary"}
  ],
  "stage_specific": {
    "compile_rounds": 1,
    "smoke_pass_count": 5,
    "total_cases": 20, "pass_count": 20, "fail_count": 0,
    "stimulus_iterations": 0,
    "coverage_summary": {
      "line": 92, "cond": 71, "fsm": 64, "toggle": 88
    }
  }
}
```

> `artifacts[]` per the envelope schema is an array of objects (`{path, kind}`), not a bare string
> array. Every path above MUST appear in `result.json.artifacts[]`, otherwise it is not promoted to
> canonical (external read-only consumption of canonical `filelist.f` / `tb/uvm/`, etc. would fail).
> `verify-handoff.json` is an intra-stage handoff, not a promoted deliverable — the orchestrator does
> not list it in `artifacts[]`.

## Forbidden outputs

- Do not write `verification-plan.md` / `scaffold-specification.json` (plan is a read-only external
  reference).
- Do not modify any file under `Design/rtl-design/`.
