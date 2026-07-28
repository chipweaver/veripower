# lint-cdc — Makefile and Bootstrap quick reference

Source of truth: `${CLAUDE_SKILL_DIR}/templates/`.

## Bootstrap

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py bootstrap \
     --module <module-dir-name> --workdir <workdir> [--top <top-module>]
```

- Deploys into the directory passed via `--workdir` (typically `asic/<module>/Design/lint-cdc/runs/<N>/`, caller-provided). A relative `--workdir` resolves against the working tree root (the CWD, i.e. the directory containing `asic/`).
- Substitutes the `MY_TOP` placeholder in: `env.sh`, `scripts/spyglass_lint.prj`, `scripts/constraints.sgdc`, `scripts/waiver.tcl` — except entries already present in the workdir (a carried file — see below — copied verbatim by `carry_self` before this verb runs), which are left untouched (no-clobber deploy).
- The canonical `Design/lint-cdc/scripts/waiver.tcl` is carried into every new workdir verbatim by kernel.py's `carry_self`, BEFORE this verb runs — the human-reviewed waivers persisted by a prior run survive into each new deploy instead of being reset to the pristine template; the no-clobber deploy is what lets that carried file win.
- RTL paths in `scripts/filelist.txt` are the ABSOLUTE rtl-design stage root injected into `<workdir>/inputs.json`'s `"rtl"` key (no relpath climb, no self-navigation).
- An existing `{workdir}/Makefile` is treated as "already deployed" and the script aborts; a caller-placed `directive.md` inside the workdir does NOT count as "deployed".
- When `--top` is omitted, the script infers it from `<rtl_doc>/README.md` or `<rtl>/filelist.txt`.

## SGDC source selection

The lint-cdc bootstrap verb resolves the SGDC seed in carried → cold → template priority order:

> The SKILL invocation flow's Step 1 prerequisite check already fail-closes on "neither carried nor cold available" (see `SKILL.md` Step 1 and the Input Artifacts table); the "neither" row in the table below applies only to ad-hoc invocations (e.g., manual template testing).

| Path | Source | Trigger condition | Behavior |
|---|---|---|---|
| carried | `{workdir}/scripts/constraints.sgdc` | Already present in the workdir — `carry_self` copied the SGDC with depth annotations from a previous passing lint-cdc run's canonical (the run listed this entry in `result.json.artifacts[]`) BEFORE this verb ran. | Left untouched by the no-clobber deploy; do **not** substitute `MY_TOP`. The next iteration inherits every already-converged `sync_cell` / `reset_synchronizer` / `set_case_analysis` / `quasi_static`. |
| cold | `<sgdc_seed>/constraints/<TOP>.sgdc` (injected `inputs.json` location) | No carried file yet, but the specification stage has persisted a seed. | Copy to `scripts/constraints.sgdc`; do **not** substitute `MY_TOP`. This round must re-iterate the depth annotations. |
| template | `templates/scripts/constraints.sgdc` | Neither carried nor cold available (ad-hoc invocation / template testing). | Use the template with `MY_TOP` substituted; clock / reset constraints must be added by hand. |

`<sgdc_seed>/constraints/<TOP>.sgdc` is always the seed source of truth (specification persists it once, then it is frozen); you **do not** write back to that source of truth. The SGDC with depth annotations is listed in `result.json.artifacts[]` and lands at this stage's own canonical (`Design/lint-cdc/scripts/constraints.sgdc`), which `carry_self` uses as the next run's carry-forward anchor.


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
