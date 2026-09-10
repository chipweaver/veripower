# Coverage iteration: stimulus gap or intent gap

## What you read

`structural-coverage.json` carries two things you need. `per_module` holds the per-dimension
percentages per instance tree, and the DUT's own row there is what the coverage gate scores
against the bounds the engineer wrote — not the `aggregate` block beside it, which covers the TB
top's whole tree including the agent interfaces and any ROMs, and so answers a question no row
asked. The bounds are the
`<requirements>/requirements.json` rows simulation judges that carry a `target`, which is what
decides pass or fail — and a row whose `target.dim` names something this stage does not measure
fails by name rather than going unnoticed. `uncovered[]` holds the named items behind those percentages, one entry per
branch, condition or FSM transition urg saw and never exercised:

```json
{"module": "mgpt_rmsnorm", "kind": "branch", "line": 160, "detail": "div_q > QMAX"}
```

A percentage tells you a dimension is short; only `uncovered[]` tells you what to write stimulus
for. `per_module` breaks the percentages down, which is how you find the child dragging a dimension.

## Classification (your judgment, not a string match)

For each uncovered item, decide whether some entry in `tb-scaffold.json.testpoints[]` set out to
exercise it. There is no key to join on — the plan speaks in situations, urg in source lines — so
you are reading the item's module, line and condition text against what each testpoint says it
drives (`intent`), and asking whether it falls inside that.

- **Stimulus-layer gap:** a testpoint does claim it, and the sequence written for that testpoint
  never drove the design through it.
- **Intent-layer gap:** no testpoint claims it, or you cannot tell which one would. Route out.

## Stimulus iterate flow

While every uncovered item is a stimulus-layer gap:

1. For each item, find the testpoint that claims it and the sequence wired toward it
   (`testpoints[].seqs` names them).
2. Under `tb/uvm/<module>/seq/`, add seeds, tighten that sequence's constraint parameters, or append
   a testcase to `tests/testlist.json` (append only: do not change the semantics of existing
   entries).
3. Re-run `make regress` and read the new `structural-coverage.json`.
4. Every bounded dimension satisfying its row means coverage converged.
5. If gaps remain, classify them again and continue adjusting stimulus for those within the plan.

## Routing out

You do not write `result.json`. You route out by returning your `STATUS` last line plus a JSON line
carrying the failure fields, which the orchestrator maps into a `status=fail` envelope with
the coverage route-out.

- **Any intent-layer gap**, whether or not stimulus-layer gaps sit beside it:
  `gaps_not_in_testpoints`.
- Include any remaining stimulus-layer gaps in `gaps_in_testpoints`.

## Threshold source

The engineer's own rows in `<requirements>/requirements.json`: `judge` simulation with a
`target`, compared with the row's own `op`. The dimensions this stage measures are
`coverage_line` / `coverage_cond` / `coverage_fsm` / `coverage_toggle`; a row naming any other
dimension is refused by name here, because a bound nothing compares is a bound the engineer
wrote and nobody kept. A dimension no row bounds is reported and not gated.
