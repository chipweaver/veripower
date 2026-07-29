# Rule B: Stimulus vs. Intent coverage iteration

## Classification (mechanical)

Read `structural-coverage.json` (the urg-derived structural coverage file; use the `aggregate` block for dimension totals and `per_module` for per-module breakdowns) and list the uncovered bins. For each uncovered bin:

1. Look up the bin in the flat fields under `tb-scaffold.json.testpoints[].bins[]` (matched by the bin naming convention).
2. Match → **stimulus-layer gap** (can be closed by adding stimulus in simulation).
3. No match → **intent-layer gap** (route out — see below).

## Stimulus iterate flow

Provided "all uncovered bins are inside scaffold testpoints" holds, run at most `defaults.yaml.stimulus_iterate_max_rounds` rounds:

1. Analyze the testpoint description and sequence corresponding to each uncovered bin.
2. Under `tb/uvm/<module>/seq/`, add new seeds / tighten sequence constraints / append new testcases (write into `tests/testlist.json` — **append only**; do not change the semantics of existing entries).
3. Re-run `make regress` and read the new `structural-coverage.json`.
4. If every dimension now meets the threshold → coverage converges.
5. If gaps remain → repeat, until thresholds are met or the budget is exhausted.

## Fail-trigger conditions

You do not write `result.json`; you **route out** by returning your `STATUS` last line plus a JSON line carrying the failure fields in `stage_specific` (the orchestrator maps these into the `status=fail` envelope with `failure_phase=coverage`).

- **Any uncovered bin is not inside `tb-scaffold.json.testpoints[].bins[]`** → route out with `failure_phase=coverage` + `coverage_gaps` + `gaps_not_in_testpoints` (intent gap).
- **`defaults.yaml.stimulus_iterate_max_rounds` rounds exhausted with stimulus-layer gaps still present** → route out with `failure_phase=coverage` + `coverage_gaps` + `gaps_in_testpoints` (whether the cause is RTL unreachability vs. an insufficient stimulus plan is for the caller to decide).

## Threshold source

`${CLAUDE_SKILL_DIR}/defaults.yaml.coverage_thresholds` (i.e. `skills/simulation/defaults.yaml`). Every dimension's threshold is hard-coded in that file; per-module override is not supported.
