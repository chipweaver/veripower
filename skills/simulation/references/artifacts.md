# Simulation artifacts

All paths are relative to `{workdir}`.

| Artifact | Purpose |
|---|---|
| `logs/<test>.status` | Test-written `PASS` or `FAIL`; a missing status means incomplete execution. |
| `regression-log.txt` | `RESULT` lines from the latest `make smoke` or `make regress`; the latter replaces the smoke summary. |
| `structural-coverage.json` | URG instance subtrees in `per_instance`, keyed by full path, plus `uncovered[]` items. The gate judges `<top>_tb_top.u_dut`, using the scaffold's RTL `top`. |
| `cov_merge/` | Original URG reports. |
| `case-results.json` | Suite counts from `write_summary.py`, using the regression log and test roster. Read by finalize. |
| `case-results-summary.md` | Human-readable test results and failure pointers. |
| `tb/`, `tests/`, `scripts/` | Verification sources, test roster (`tests/testlist.json`), data and helpers. |
| `check-review.md` | Review findings; unresolved blocking findings use a `##` heading ending in `BLOCKING`. |
| `<test_id>.fsdb` | Failing-test waveform at the run root. Triage reads it through `sim_run`; it is not published to the canonical tree. Passing-test waveforms are deleted. |

Finalize publishes the listed artifacts except waveforms. Keep any additional diagnostic evidence
under `evidence/`, which is also published.
