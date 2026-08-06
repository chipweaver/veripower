# Rule B: Stimulus vs. Intent coverage iteration

## What you read

`structural-coverage.json` carries two things you need. `aggregate` holds the per-dimension
percentages the coverage gate scores against `defaults.yaml.coverage_thresholds`, which is what
decides pass or fail. `uncovered[]` holds the named items behind those percentages, one entry per
branch, condition or FSM transition urg saw and never exercised:

```json
{"module": "mgpt_rmsnorm", "kind": "branch", "line": 160, "detail": "div_q > QMAX"}
```

A percentage tells you a dimension is short; only `uncovered[]` tells you what to write stimulus
for. `per_module` breaks the percentages down, which is how you find the child dragging a dimension.

## Classification (your judgment, not a string match)

For each uncovered item, decide whether some entry in `tb-scaffold.json.testpoints[]` set out to
exercise it. `testpoints[].bins[]` are conceptual tags the plan author chose (`handshake`,
`saturation`, `position-sweep`), not urg's identifiers, so there is no key to join on: you are
reading the item's module, source line and condition text and asking whether it falls inside what
that testpoint describes itself as driving (`intent`) and covering (`bins`).

- **Stimulus-layer gap:** a testpoint does claim it, and the sequence written for that testpoint
  never drove the design through it.
- **Intent-layer gap:** no testpoint claims it, or you cannot tell which one would. Route out.
  Uncertainty belongs on this side: the other side spends the iterate budget trying to close a hole
  no testpoint was ever going to close, and then reports the budget as exhausted, which sends the
  rework somewhere else again.

## Stimulus iterate flow

Only while every uncovered item is a stimulus-layer gap, and for at most
`defaults.yaml.stimulus_iterate_max_rounds` rounds:

1. For each item, find the testpoint that claims it and the sequence wired toward it
   (`verify-handoff.json` maps testpoint to sequence).
2. Under `tb/uvm/<module>/seq/`, add seeds, tighten that sequence's constraint parameters, or append
   a testcase to `tests/testlist.json` (append only: do not change the semantics of existing
   entries).
3. Re-run `make regress` and read the new `structural-coverage.json`.
4. Every dimension at or above threshold means coverage converged.
5. Gaps remaining means repeat, until the thresholds are met or the budget is spent.

## Routing out

You do not write `result.json`. You route out by returning your `STATUS` last line plus a JSON line
carrying the failure fields, which the orchestrator maps into a `status=fail` envelope with
the coverage route-out.

- **Any intent-layer gap**, whether or not stimulus-layer gaps sit beside it: `coverage_gaps` +
  `gaps_not_in_testpoints`. The intent gap goes first; iterating stimulus in the same round would
  spend budget on a plan defect.
- **Budget spent with stimulus-layer gaps left:** `coverage_gaps` + `gaps_in_testpoints`. Whether
  the cause is an insufficient stimulus plan or RTL the design can never reach is for the caller to
  decide, and it is why these two lists are separate.

## Threshold source

`${CLAUDE_SKILL_DIR}/defaults.yaml.coverage_thresholds`. Every dimension's threshold is fixed there;
per-module override is not supported.
