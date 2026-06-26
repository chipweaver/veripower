# lint-cdc stage project templates

This directory holds the `veripower:lint-cdc` stage's project templates, at
`${CLAUDE_SKILL_DIR}/templates/`. The stage SOP lives in
`${CLAUDE_SKILL_DIR}/SKILL.md`; the deployment + Makefile-target quick reference
lives in `${CLAUDE_SKILL_DIR}/references/makefile-bootstrap.md`.

## Deployment

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py bootstrap \
     --module <module-dir-name> --workdir <abs-path> [--top <top-module>]
```

Deployment target: the directory passed via `--workdir` (typically
`asic/<module>/Design/lint-cdc/runs/<N>/`, caller-provided).

When `--top` is omitted, the script infers the top-module name from
`Design/rtl-design/README.md` or `filelist.txt`; if inference fails, pass
`--top` explicitly. An existing `{workdir}/Makefile` is treated as "already
deployed" and the script aborts (a caller-placed `orchestrator-context.md`
inside the workdir does NOT trigger this check); back up first and clean up
manually or merge.

## Files to edit after deployment

| File | Required content |
|---|---|
| `scripts/filelist.txt` | Synced by bootstrap from `Design/rtl-design/filelist.txt`; add `+incdir+` header search paths if needed. |
| `scripts/constraints.sgdc` | Bootstrap fills it from the SGDC seed (warm → cold → template; see `references/makefile-bootstrap.md`). If neither warm nor cold exists, follow the template to add clock / reset / port constraints. |
| `scripts/waiver.tcl` | Add reviewed waivers (rule ID, reason, owner, date). |

## File descriptions

| File | Description |
|---|---|
| `env.sh` | Environment variables: `TOP`, `SPYGLASS_STAGE`, `SPYGLASS_TIMEOUT`. |
| `Makefile` | Build entry point; manages every make target. |
| `scripts/spyglass_lint.prj` | SpyGlass project file (`#!SPYGLASS_PROJECT_FILE` format). |
| `scripts/filelist.txt` | RTL file list (sourcelist format). |
| `scripts/constraints.sgdc` | Clock / reset / port constraints (SGDC format). |
| `scripts/waiver.tcl` | Lint / CDC waiver definitions. |
| `scripts/run_spyglass.sh` | SpyGlass `-shell -tcl` entry point (always invokes `run.tcl`; `SPYGLASS_STAGE` selects the subset). |
| `scripts/run.tcl` | SpyGlass lint / CDC entry point (`SPYGLASS_STAGE=lint\|cdc\|all` corresponds to `make lint` / `make cdc` / `make all`). |
| `scripts/collect_report.py` | Locates the SpyGlass report in `spyglass_work/` (param `{lint\|cdc}`) and emits `{lint\|cdc}-report.txt` + `{lint\|cdc}-violations.json`; fail-loud (exit 1 missing / exit 3 unparseable or count-mismatch). |

## Placeholder substitution

During deployment, the lint-cdc bootstrap verb substitutes `MY_TOP` with the
actual top-module name in: `env.sh` / `scripts/spyglass_lint.prj` /
`scripts/filelist.txt` / `scripts/constraints.sgdc` / `scripts/waiver.tcl`.
When the warm SGDC (`Design/lint-cdc/scripts/constraints.sgdc`) or the cold
SGDC (`Design/specification/constraints/<TOP>.sgdc`) is present and copied
in as `scripts/constraints.sgdc`, that file is already bound to a concrete
top-module name and no `MY_TOP` substitution is needed.
