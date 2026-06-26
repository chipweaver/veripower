# lint-cdc — Makefile and Bootstrap quick reference

Source of truth: `${CLAUDE_SKILL_DIR}/templates/`.

## Bootstrap

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py bootstrap \
     --module <module-dir-name> --workdir <abs-path> [--top <top-module>]
```

- Deploys into the directory passed via `--workdir` (typically `asic/<module>/Design/lint-cdc/runs/<N>/`, caller-provided).
- Substitutes the `MY_TOP` placeholder in: `env.sh`, `scripts/spyglass_lint.prj`, `scripts/filelist.txt`, `scripts/constraints.sgdc`, `scripts/waiver.tcl`.
- RTL paths in `scripts/filelist.txt` are written as `../../../rtl-design/...` (relative to the sourcelist file `scripts/filelist.txt`: scripts/ → runs/<N>/ → lint-cdc/ → Design/ → rtl-design/).
- An existing `{workdir}/Makefile` is treated as "already deployed" and the script aborts; a caller-placed `orchestrator-context.md` inside the workdir does NOT count as "deployed".
- When `--top` is omitted, the script infers it from `Design/rtl-design/README.md` or `filelist.txt`.

## SGDC source selection

The lint-cdc bootstrap verb resolves the SGDC seed in warm → cold → template priority order:

> The SKILL invocation flow's Step 1 prerequisite check already fail-closes on "neither warm nor cold available" (see `SKILL.md` Step 1 and the Input Artifacts table); the "neither" row in the table below applies only to ad-hoc invocations (e.g., manual template testing).

| Path | Source | Trigger condition | Behavior |
|---|---|---|---|
| warm | `Design/lint-cdc/scripts/constraints.sgdc` | The SGDC with depth annotations persisted by a previous passing lint-cdc run (the run listed this entry in `result.json.artifacts[]`). | Copy to `scripts/constraints.sgdc`; do **not** substitute `MY_TOP`. The next iteration inherits every already-converged `sync_cell` / `reset_synchronizer` / `set_case_analysis` / `quasi_static`. |
| cold | `Design/specification/constraints/<TOP>.sgdc` | No warm available, but the specification stage has persisted a seed. | Copy to `scripts/constraints.sgdc`; do **not** substitute `MY_TOP`. This round must re-iterate the depth annotations. |
| template | `templates/scripts/constraints.sgdc` | Neither warm nor cold available (ad-hoc invocation / template testing). | Use the template with `MY_TOP` substituted; clock / reset constraints must be added by hand. |

`Design/specification/constraints/<TOP>.sgdc` is always the seed source of truth (specification persists it once, then it is frozen); this stage **does not** write back to that source of truth. The SGDC with depth annotations is listed in `result.json.artifacts[]` and lands at this stage's own canonical (`Design/lint-cdc/scripts/constraints.sgdc`), which serves as the next run's warm-start anchor.

After deployment, the script also cross-checks the first clock `-period` in the spec source-of-truth `<TOP>.sgdc` against `<TOP>.sdc`; on mismatch it prints a `WARNING` only and does not abort — consistency issues are a `specification` rework.

## Makefile (`asic/<module>/Design/lint-cdc/runs/<N>/`)

| Target | Description |
|---|---|
| `make lint` | SpyGlass Lint (goal `lint/lint_rtl`); produces `lint-report.txt`. |
| `make cdc` | SpyGlass CDC three phases (`cdc_setup` → `cdc_setup_check` → `cdc_verify_struct`); produces `cdc-report.txt`. |
| `make all` | Lint + CDC in a single session; both reports are produced together (recommended for the first full run). |
| `make lint-report` | Aggregate the already-generated SpyGlass output into `lint-report.txt` + `lint-violations.json`. |
| `make cdc-report` | Aggregate the already-generated SpyGlass output into `cdc-report.txt` + `cdc-violations.json`. |
| `make clean` | Clean intermediate artifacts and reports. |

> `make cdc` is independently runnable at the tool layer (`cdc_setup` carries its own `elaborate`); it is preferable to run `make lint` first so `set_case_analysis` converges before running `make cdc`, which avoids leftover test-control-signal noise in the CDC report, or to run `make all` once (a single session sharing `elaborate`).

## Report aggregation

`scripts/collect_report.py {lint|cdc}` (run from the `runs/<N>/` workdir by the `lint-report` / `cdc-report` Makefile targets) locates the SpyGlass source report under `spyglass_work/`, writes the human `{lint|cdc}-report.txt`, and writes the structured `{lint|cdc}-violations.json` (`counts` + `violations[]`). It is **fail-loud**: exit 1 `FAIL=missing` (no source report), exit 3 `FAIL=unparseable` (no `Number of Reported Messages` header, an `[ID]` row that does not parse, or an unrecognized severity token) or `FAIL=count_mismatch` (parsed `[ID]` rows ≠ reported total, `generated ≠ waived + reported`, or overlimit-suppressed messages). It removes prior outputs at the start of every run and writes both only on exit 0, so a stale artifact never survives a failed re-run. SKILL.md Step 4 / Step 5 map each `FAIL=` token to a `status=fail` `fail_reason`; a non-zero `make` must never be treated as lint / CDC sign-off pass.
