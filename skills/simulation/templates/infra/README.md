# simulation stage template root

This directory is the deployment template for the `veripower:simulation` skill, copied by the sim bootstrap verb into the simulation stage's per-run workdir: `asic/<module>/Verification/simulation/runs/<N>/` (workdir is supplied by the caller; on stage completion the caller promotes the workdir content to the canonical `Verification/simulation/`).

- Stage SOP: `skills/simulation/SKILL.md`
- Artifact contract: `skills/simulation/references/artifact-contract.md`
- Plan contract (consumer contract): `skills/simulation-plan/references/spec-input-contract.md`

## Automatic deployment

Invoked by the env-build child (dispatched at stage SOP Step 2):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/simulation/scripts/sim/__main__.py bootstrap \
    --module <module-dir-name> --workdir <caller-provided per-run workdir> [--top <top-module-name>] \
    --scaffold asic/<M>/Verification/simulation-plan/scaffold-specification.json
```

Bootstrap behavior:

1. Copy this directory to `{workdir}`; sed-substitute `MY_TOP` / `MY_MODULE` / `MY_RTL_DIR` / `MY_SPEC_DIR` (the latter two are computed by bootstrap from workdir depth).
2. Generate `rtl_filelist.f` from `Design/rtl-design/filelist.txt` (paths prefixed by `MY_RTL_DIR` — the workdir → rtl-design relative path).
3. Create empty directories `tb/uvm/{interface,transaction,agent,checker,refmodel,env,seq,test,pkg,top}/`.
4. When `--scaffold` is provided, the bootstrap verb renders the scaffold to generate the full UVM scaffold from `scaffold-specification.json` (agent / driver / monitor / refmodel / scoreboard / env / tb_top / tb_pkg / filelist / generated_tests / tests/testlist.json).

If `{workdir}/Makefile` already exists → bootstrap aborts to avoid overwriting (when creating the workdir, the caller may place hint files such as `orchestrator-context.md`; those do not constitute "already deployed").

## Template responsibilities

| File / Directory | Role |
|---|---|
| `Makefile` | `make simv` / `make smoke` / `make regress` / `make run_test` / `make coverage-summary` / `make summary`. |
| `env.sh` | `MODULE` / `TOP` / `SPEC_DIR` / `RTL_DIR` / `UVM_HOME` / VCS-related environment variables. |
| `filelist.f` | VCS top-level filelist (**not in the infra template** — rendered by scaffold mode from `templates/scaffold/filelist.f`). |
| `rtl_filelist.f` | Placeholder file; at bootstrap, overwritten by the derivation from `Design/rtl-design/filelist.txt`. |
| `tb/uvm/seq/base_seq.sv` | UVM base sequence; the `<seq>` classes scaffold generates inherit from it. |
| `tb/uvm/test/base_test.sv` | UVM base test; the `<test>` classes scaffold generates inherit from it. |
| `tests/` | Testcase metadata directory; in scaffold mode, `testlist.json` is written here. |
| `scripts/run_vcs_regression.sh` | VCS compile / smoke / regress / single-test entry point; emits stable `RESULT` lines consumed by `write_summary.py`. |
| `scripts/write_summary.py` | Aggregates `coverage-summary.txt` and `case-results-summary.md` from `regression-log.txt`. |

## Post-deployment commands

```bash
cd asic/<module>/Verification/simulation/runs/<N>
make simv
make smoke
make regress
make run_test TEST=<test_id-or-uvm_testname>
make coverage-summary
make summary
```

## Placeholders

| Placeholder | Description |
|---|---|
| `MY_MODULE` | Module directory name. |
| `MY_TOP` | RTL top-module name. |
| `MY_RTL_DIR` | workdir → `asic/<M>/Design/rtl-design/` relative path (bootstrap computes with `os.path.relpath`). |
| `MY_SPEC_DIR` | workdir → `asic/<M>/Design/specification/` relative path. |

## Notes

- `verification-plan.md` / `scaffold-specification.json` live under `Verification/simulation-plan/`; simulation consumes them read-only — any modification is treated as a contract violation (see `references/repair-boundaries.md` and `references/coverage-iteration.md`).
- VCS / UVM entry needs `UVM_HOME`; `env.sh` errors out when it is missing.
- The `RESULT` line format in `run_vcs_regression.sh` is consumed by `write_summary.py` — do not change field order or keywords.
