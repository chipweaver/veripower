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

Shared helpers live in `skills_source.py`; fixtures live beside the tests that use them.

Report parser fixtures isolate tool syntax and measurement semantics. They do not
encode a benchmark design or set acceptance thresholds from its measurements.
Native tool and benchmark experiments live under [experiments/](../experiments/).

Use controlled tool responses to test entrypoint routing and error propagation.
Those tests exercise the shipped scripts; they do not claim the tool ran or the
hardware passed. Keep native report fragments needed for syntax and unit handling;
archive full design experiments separately.
