---
name: power-analysis
description: Use when running gate-level power simulation + PT-PX averaged power analysis (SAIF flow) for PPA gating; not for RTL functional simulation, static timing, or time-resolved waveforms.
---

# Power Analysis

This skill's sole responsibility: run VCS gate-level simulation against the post-synthesis netlist trio and the UVM TB infrastructure to produce SAIF, then run PrimeTime PX in averaged mode over each SAIF to compute `power_mw`; self-judge the `power_mw` PPA dimension.

## When to Use

- First-time setup of the GLS power simulation + PT-PX averaged power-analysis environment.
- End-to-end run: bootstrap (first-run only) → `make all` (tb-shim + refresh-tests → gls-compile → gls-run → ptpx) → write `result.json`.
- Re-run after a dependency artifact change: any change to the synthesized netlist / SDF / `power_scenarios[]` / TB infrastructure.
- Multi-scenario sweep: per-scenario SAIF per `power_scenarios[]` entry, each with its own `reports_ptpx/<id>/`.

## Iron Rule

- Do not modify any file under `Verification/simulation/` / `Verification/simulation-plan/` / `Design/synthesis/` / `Design/rtl-design/` — these are read-only external references for power-analysis (contract violation — source-of-truth corruption).
- Power test classes (`power_<seq>_test.sv`) are **auto-generated** by this stage — do not hand-write them or reuse power tests from any other source. Internally, each test reuses the `{module}_<seq>_seq` class already compiled by simulation (the plan's `power_scenarios[].sequence_ref` and `sequences[].name` share a namespace); this stage does NOT render an independent sequence class (contract violation — multi-source power tests cause naming / semantic drift).
- The TB emits SAIF directly via `$set_gate_level_monitoring + $toggle_*` — `$dumpfile / $dumpvars` are **forbidden** (architectural violation — the SAIF path does not go through VCD; direct toggle dump avoids intermediate-format loss).
- `ptpx.tcl` locks `power_analysis_mode averaged` + `read_saif`; the 0% Annotated cell percentage gate MUST be preserved: PT-PX triggers `exit 1` when 0% annotation is detected at the end of the batch (contract violation — silently passing on 0% annotation is equivalent to power-data corruption).
- On failure, `failures[].{phase, category, error_summary}` MUST be filled in (contract violation — missing categorization makes the root cause unidentifiable).
- `hier_separator` MUST be explicitly set to `"/"` at the top of `ptpx.tcl`: write both `catch {set_app_var hier_separator "/"}` + `set hier_separator "/"` — PT M-2016 treats this as a Tcl global (`set_app_var` reports CMD-104), while newer PT treats it as an application var; the default dot-separated value causes `strip_path` to silently mismatch (contract violation — power hierarchy paths become unresolvable).

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{orchestrator_context_path}` | Optional. Caller-injected fix-scope hint file path. This stage NEVER receives `{rework_trigger}` injection (this stage is not itself a valid fix target); only `{orchestrator_context_path}` may be injected (carrying a reasoning hint for either first-run or rework). |

### External reference inputs

| Path | Schema / Format | Required | Use |
|---|---|---|---|
| `Verification/simulation/result.json` | simulation envelope | required (first-run) | simulation envelope (`status=pass` gate). |
| `Verification/simulation/filelist.f` | UVM filelist | required (first-run) | TB infrastructure compile list (read-only). |
| `Verification/simulation/tb/uvm/**/*.sv` | UVM SystemVerilog | required (first-run) | TB infrastructure (`tb_top` / `env` / agents, etc.; referenced by `filelist.f` and read indirectly). |
| `Verification/simulation-plan/scaffold-specification.json` | simulation-plan schema | required (first-run) | `power_scenarios[]` list (drives `emit_power_tests` + `run_gls_power`). |
| `Design/synthesis/out/<TOP>_syn.v` | structural Verilog | required (first-run) | Synthesized netlist (VCS GLS compile + PT-PX `read_verilog`). |
| `Design/synthesis/out/<TOP>_syn.sdc` | SDC | required (first-run) | PT-PX `read_sdc` (constraint propagation). |
| `Design/synthesis/out/<TOP>_syn.sdf` | SDF v3.0 | required (first-run) | VCS SDF back-annotation delay + PT-PX `read_sdf` (state-dependent leakage). |
| `Design/timing-analysis/result.json` | timing-analysis envelope | required (first-run) | timing-analysis envelope (`status=pass` gate). |
| `LIB_V` (env) | std cell Verilog model path | required (first-run) | linked against the netlist at VCS compile time. |
| `LIB_DB` (env) | std cell Liberty `.db`/`.lib` | required (first-run) | PT-PX activity→power mapping (MUST match what was used at synthesis). |
| `UVM_HOME` (env) | UVM library path | required (first-run) | matches what TB infrastructure was built against. |

`ppa_targets` (entries on the `power_mw` dimension only) is injected by the caller in the prompt.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope.schema.json | This stage's status contract (includes `saif_artifacts[]` / `compile_info` / `failures[]` / `ppa_actual[]` / `violations[]` / `power_by_corner[]`). |
| `env.sh` | shell | Environment variables. |
| `Makefile` | make | `tb-shim` + `refresh-tests` + `gls-compile` + `gls-run` + `ptpx` + `all` entry point. |
| `scripts/emit_power_tests.py` | python | Called by bootstrap + by `make refresh-tests`: renders power test classes from `power_scenarios[]`. |
| `scripts/build_tb_filelist_abs.py` | python | Called by `make tb-shim`: rewrites `simulation/filelist.f` to an absolute-path version (drops `-f rtl_filelist.f` so GLS uses the netlist in place of RTL). |
| `scripts/run_gls_power.sh` | shell | Per-scenario `simv` dispatch (dedup via `sequence_ref` hardlink). |
| `scripts/extract_power_scenarios.py` | python | Internal to `run_gls_power.sh`: emits one `<id>\t<sequence_ref>` row per `power_scenarios[]` entry; never invoked directly. |
| `scripts/check_sdf_annotated.sh` | shell | Internal to `make gls-compile`: gates on the SDF annotation summary in `gls-compile-log.txt` (0 annotated = fail); never invoked directly. |
| `scripts/ptpx.tcl` | TCL | PT-PX averaged main script (single session loads the design + iterates all SAIFs in `SAIF_LIST`). |
| `scaffold/power_test.sv.tmpl` | template | UVM test template (contains `$set_gate_level_monitoring + $toggle_*`; placeholders `{{MODULE}}` / `{{AGENT_NAME}}` / `{{SEQUENCE_REF}}` / `{{TOP}}`, etc. are substituted at render time). |
| `scaffold/power_tests/power_<seq>_test.sv` | UVM SV | Auto-generated test class (`import {module}_tb_pkg`, `extends {module}_base_test`, calls the `{module}_<seq>_seq` already compiled by simulation). |
| `scaffold/power_filelist.f` | filelist | Power-tests file list (VCS `-f` input). |
| `tb_filelist_abs.f` | filelist | Absolute-path rewrite of the simulation TB filelist (VCS `-f` input; produced by `make tb-shim` before every `gls-compile`). |
| `simv` | VCS binary | GLS compile output. |
| `simv.daidir/` | VCS internal | VCS working directory. |
| `saif/<id>.saif` | SAIF | Per-scenario gate-level SAIF (hardlinked to `_dedup/<seq>.saif`). |
| `saif/_dedup/<sequence_ref>.saif` | SAIF | Dedup canonical. |
| `reports_ptpx/<id>/power_hier.rpt` | PT text | Power hierarchy report. |
| `reports_ptpx/<id>/power_flat.rpt` | PT text | Power flat report. |
| `reports_ptpx/<id>/switching_activity.rpt` | PT text | Switching-activity report. |
| `reports_ptpx/<id>/ptpx.log` | text | Per-SAIF PT-PX run log. |
| `gls-compile-log.txt` | text | `vcs` compile log. |
| `gls-run-log.txt` | text | Run-scenarios aggregate log. |
| `ptpx.log` | text | Single `pt_shell` whole-session log (design loading + batch SAIF processing summary). |

## Workflow

`{workdir}` is provided empty; bootstrap is mandatory on first run. `make refresh-tests` re-renders power tests from the current plan before every `gls-compile`.

### Step 1: Pre-check external references

Confirm `Verification/simulation/result.json.status=pass` AND `Design/timing-analysis/result.json.status=pass` AND `Verification/simulation/filelist.f` / `scaffold-specification.json` (non-empty `power_scenarios[]`) / the synthesis trio (`<TOP>_syn.{v,sdc,sdf}`) present AND `LIB_V`/`LIB_DB`/`UVM_HOME` set with valid paths. Any miss → write `status=fail` + `failure_kind="infra"` + `fail_reason="external reference missing/not pass: <path>"` and exit. When `{orchestrator_context_path}` is injected, Read it first as a fix-scope hint.

### Step 2: Bootstrap (first-run only)

`bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap_power_analysis.sh --module {module} --workdir {workdir} [--top <TOP>]`. Copies `templates/`, substitutes placeholders, renders power tests. Aborts if a `Makefile` is already deployed (incremental updates go through `make refresh-tests`).

### Step 3: Run and judge

`cd {workdir} && make all >make.out 2>&1` (redirect keeps the multi-thousand-line VCS/PT logs out of context; each stage still tees to its own log file).

- **`make` exited non-zero** → read a **bounded** slice of the failing stage's log (`gls-compile-log.txt` / `gls-run-log.txt` / `ptpx.log`) — never the whole dump. Determine the failure's **`category`**:
  1. If a `make` step already printed `phase=<p> category=<x>` (SDF-0 → `phase=compile`/`category=sdf`; `SAIF empty` → `phase=run`/`category=saif_dump`; `annotated 0%` → `phase=ptpx`/`category=ptpx_data`; PT design-load → `phase=ptpx`/`category=netlist`|`sdf`), **copy both verbatim**.
  2. Otherwise (a VCS compile error → all `phase=compile`) classify by the **named file's directory**:

  | error names a file under… | category |
  |---|---|
  | `Design/synthesis/out/*.v` | `netlist` |
  | `Design/synthesis/out/*.sdf` | `sdf` |
  | TB filelist roots (`Verification/simulation/...`) or local `power_filelist.f` | `tb_uvm` |
  | no named file / VCS flag / `UVM_HOME` / license error | `tooling` |

  Write `status=fail` + `failure_kind` (`infra` for missing-reference/license; else `tooling`) + `failures[].{phase, category, error_summary}` + `fail_reason`. **Write only the failure facts (`phase` / `category`); do NOT assign any rework or routing target — target selection is owned downstream, outside this stage.**

- **`make` exited 0** → run the verdict script:

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/power_rpt_parser.py \
      --plan Verification/simulation-plan/scaffold-specification.json \
      --workdir {workdir} --targets '<ppa_targets JSON from prompt>' \
      --out {workdir}/power-actual.json
  ```

  - **exit 0** → read `{workdir}/power-actual.json`, fold its `stage_specific` fields in, and adopt its `verdict`: `pass` → `status=pass`; `fail` (a `power_mw` miss) → `status=fail` + `failure_kind="ppa"` + its `violations[]` + a one-line `fail_reason`.
  - **non-zero exit** → the script is authoritative (never infer pass from report presence). Read its `FAIL=<token>` and fold the `failures[]` it wrote: `status=fail` + `failure_kind="tooling"` + `fail_reason` from the token.

### Step 4: Write `{workdir}/result.json`

(schema: `references/result.schema.json` + envelope). On `status=pass`, the schema requires `stage_specific.{saif_artifacts, compile_info, failures, ppa_actual, violations, power_by_corner}` (all folded from `power-actual.json`). On `status=fail`, it requires `stage_specific.{fail_reason, failure_kind}` (`failure_kind ∈ {infra, tooling, ppa}`; on `tooling`, `failures[]` required; on `ppa`, the six fields + `violations[]`). List every on-disk artifact in `artifacts[]`.

## Red Flags

| Excuse | Reality |
|---|---|
| "Annotation/SAIF looks empty (0 elements / `size=0` / 0% annotated) but the flow ran — mark pass" | Each is a hard sanity failure: SDF 0 → `status=fail` `category=sdf`; SAIF `size=0` → `failures[]` `category=saif_dump`; PT-PX 0% → `exit 1` + `status=fail` `category=ptpx_data`. Silently passing on no annotation is power-data corruption. |
| "`power_mw` is a little over target — pass" | PPA self-check is mandatory: a `power_mw` miss → `status=fail` + `violations[]` (one entry each), kept strictly separate from `failures[]` (`failures[]` = process/data failures; `violations[]` = PPA targets missed). |

## Pitfalls

| Mistake | Fix |
|------|------|
| Reports from multiple scenarios all land under `reports_ptpx/` and overwrite each other | Every SAIF MUST have its own `reports_ptpx/<id>/` subdirectory. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written and passes schema validation (`references/result.schema.json`).
- [ ] Every artifact path is listed in `result.json.artifacts[]`.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] The `result.json.status` decision has been written (`pass` or `fail`; the envelope does not accept `blocked`); on `fail`, `stage_specific.{fail_reason, failure_kind}` are required (`failure_kind ∈ {infra, tooling, ppa}`); on `failure_kind="tooling"`, `failures[]` is required; on `failure_kind="ppa"`, the six fields + `violations[]` are required.
- [ ] Every `saif_artifacts[].saif_path` file exists and `size > 0`.
- [ ] Every `reports_ptpx/<id>/{power_hier.rpt, power_flat.rpt, switching_activity.rpt, ptpx.log}` is present.
- [ ] `gls-compile-log.txt` and `gls-run-log.txt` are on disk.
- [ ] `ppa_actual[]` and `power_by_corner[]` are equal-length and correspond one-to-one by `scenario_id`; every `saif_artifacts[]` entry has a matching `scenario_id` (a SAIF-empty scenario is absent from `saif_artifacts[]` but present in the other two).
- [ ] The PPA self-check has compared `power_mw`, with the result written into `ppa_actual[]` (any miss is listed in `violations[]`).
- [ ] When any scenario's parse fails, `status=fail` and that entry has `power_mw=null`.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`templates/Makefile`](templates/Makefile) — `gls-compile` + `gls-run` + `ptpx` + `all` entry point.
- `templates/scripts/emit_power_tests.py` — power test template renderer (make-internal).
- `templates/scripts/build_tb_filelist_abs.py` — absolute-path rewrite of the simulation filelist (consumed across stages by GLS; make-internal).
- `templates/scripts/run_gls_power.sh` — per-scenario `simv` dispatch (dedup via hardlink; make-internal).
- `templates/scripts/ptpx.tcl` — PT-PX averaged main script (`read_saif` + 0% annotation hard gate; make-internal).
- [`templates/scaffold/power_test.sv.tmpl`](templates/scaffold/power_test.sv.tmpl) — UVM test template (placeholders `MODULE` / `AGENT_NAME` / `SEQUENCE_REF` / `TOP` / `SCENARIO_ID` / `SCENARIO_DESC` / `DURATION_CYCLES`; contains `$set_gate_level_monitoring + $toggle_*`).
- `scripts/bootstrap_power_analysis.sh` — bootstrap script (invocation contract: Step 2 + `--help`).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- `scripts/power_rpt_parser.py` — PT-PX report parser + PPA verdict script (assembles `power-actual.json`; exit code is the pass/fail truth — mirrors `synthesis_rpt_parser.py`; invocation contract: Step 3 + `--help`).
- [`${CLAUDE_PLUGIN_ROOT}/skills/simulation-plan/references/power-scenarios-template.md`](../simulation-plan/references/power-scenarios-template.md) — `power_scenarios` field semantics.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
