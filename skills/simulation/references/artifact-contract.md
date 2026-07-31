# What each simulation product is

Who writes what is in `SKILL.md`. This says what the products *are*, where a filename does not
say it: which one a gate reads, which one is a rendering of another, which one is deliberately
not promoted. All paths are relative to `{workdir}`.

| Product | What it is |
|---|---|
| `logs/<test>.status` | `PASS` or `FAIL` per test, written by that test's own `simv` run. The smoke gate reads these and the `RESULT` lines, never a child's account of them. A test that crashed before reporting leaves none, which is a fail. |
| `regression-log.txt` | The `RESULT` lines. Written twice per round, not accumulated: `make smoke` writes the smoke lines, and `make regress` later rewrites the file with the full-regress ones. Only `logs/` persists across both. |
| `structural-coverage.json` | Urg-derived coverage. `aggregate` holds the per-dimension percentages the coverage gate scores; `uncovered[]` holds the named branch, condition and FSM items behind them, which is what Rule B classifies. This is the gate source. |
| `case-results.json` | The suite counts, derived by `write_summary.py` from `regression-log.txt` and `testlist.json`. The structured home: `sim finalize` reads its counts here and never re-parses a rendering of them. |
| `case-results-summary.md` | The rendering of `case-results.json` a human reads: per-feature traceability and, on a failure, what to open. |
| `tests/testlist.json` | The test roster. Written by env, and appended to by verify when Rule B adds a case, so its final form spans both. |
| `verify-handoff.json` | Env's note to the verify child: which sequences it wired toward each testpoint. Nothing else records that edge. |
| `conformance-review.md` | The reviewer's findings, one `##` heading each, `BLOCKING` on the ones that stop the round. The record `simulation-triage` opens when a round fails on conformance. |
| `<test_id>.fsdb` | Full-hierarchy waveform of a **failing** test, at the run-dir root rather than in `logs/`. Deliberately **not** promoted: it is large and per-run, and `simulation-triage` reaches it through `sim_run`. Passing tests' waveforms are deleted, so one exists only where something went wrong. |

Everything above except the FSDB is promoted, and `finalize` enumerates it. A product missing
from that enumeration is one the next stage cannot read even though the run passed.
