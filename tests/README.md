# Testing VeriPower

Choose tests by the behavior a change could affect. Contribution guidance lives in
[CONTRIBUTING.md](../CONTRIBUTING.md#development-and-validation).

| Location | Purpose |
|---|---|
| `unit/` | Code behavior, including CLI and adapter integration tests |
| `contracts/` | Consistency across declarations, files and documented commands |
| `scenarios/` | Agent behavior on concrete tasks; see the [scenario guide](scenarios/README.md) |

Contract checks may invoke code, for example to verify a documented CLI command.
Prefer exercising the shipped producer over reproducing its logic in a test. Review
prose quality directly; assertions about wording do not establish agent behavior.

## Run

```bash
python -m pytest tests/unit/ tests/contracts/
pre-commit run --all-files
```

Native Codex runtime checks are opt-in:

```bash
VERIPOWER_CODEX_TESTS=1 python -m pytest -q tests/unit/test_codex_runtime.py
```

These use a local Codex app-server with scripted responses. They test host mechanics,
not model reasoning or EDA quality. See [codex/README.md](../codex/README.md) for the
adapter's verification scope. Other tests may also require optional local tools;
inspect skips when interpreting a run.

Model scenarios and EDA experiments are manual checks outside the default pytest run.
Use the target platform for platform claims, and report unrun checks explicitly.

For live coverage-scope and numeric-STA regression probes, run:

```bash
python3 tests/bench/runtime_fixes.py --workdir /path/visible/to/eda/runtime-fixes
```

This uses VCS/URG, DC-Ultra and PrimeTime with the environment in `docs/eda-env.md`.
It tests distinct instances of a shared module, a combinational DUT without an FSM,
and measured setup/hold violations, including a violation rounded to zero. Reports
and verdicts stay in the workdir. `--only coverage` or `--only timing` runs one group.

Shared helpers live in `_skills_sot.py`; fixtures live beside the tests that use them.

Power refactoring uses existing implementations rather than regenerating designs. For a focused
FSA or gateGPT experiment, with the site's `LIB_V`, `LIB_DB` and EDA tools configured:

```bash
python3 tests/bench/power/run.py --case fsa --synthesis /path/to/Design/synthesis \
  --reference /path/to/fa_core_ref.c --out /path/to/new-run
```

`--case microgpt` uses `microgpt_core_ref.c`; `--sdf` can select the matching simulator export.
Check the benchmark TB's clocks against the implementation's constraints. The driver preserves
failures; register initialization is never forced. Local evidence is under
`tests/scenarios/results/power-refactor/`, `power-refactor-forward/` (i2c/usbdev, with `commands.sh`)
and `power-refactor-review/` (report, interruption and carry checks). These measurements exercise
framework behavior, not complete benchmark acceptance or physical signoff.

The independent entrypoints are additionally exercised in `power-entry-validation/`: calculation
from a new directory without SDF or experiment scripts, simulation using an existing binary,
budget-only reassessment, and rejection of invalid conditions or missing calculation inputs.
`instruction-trial/` records a separate read-only model trial on planning/rework and authorization;
it is not a new EDA run or full functional-plan acceptance.

Section 2 issue handling is checked in `tests/scenarios/results/section2-refactor/`.
`runtime/run.py` replays real coverage/case evidence through explicit orchestration fixtures and
fault injections for four benchmarks; it also checks kernel local-repair routing. The before/current
instruction trials are separate read-only decisions, not fresh hardware acceptance or a reliability
estimate. See the runtime README for the precise scope of i2c/usbdev evidence.

Authorization changes are exercised in `tests/scenarios/results/authorization-refactor/`.
The four-benchmark kernel checks use copied intents and explicit stage fixtures. Three independent
Codex contexts cover waiting for confirmation, acting under delegation and respecting withdrawal;
these are workflow exercises, not hardware signoff. Native Codex tests use scripted responses;
opencode checks resolve actual host configuration, while DeepSeek Harness checks adapter callbacks
with its real local libraries. Each evidence file states its scope.
