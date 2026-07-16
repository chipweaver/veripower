---
name: power-analysis
description: Use when running gate-level power simulation + PT-PX averaged power analysis (SAIF flow) for PPA gating; not for RTL functional simulation, static timing, or time-resolved waveforms.
---

# Power Analysis

Your sole responsibility: run VCS gate-level simulation against the post-synthesis netlist trio and the UVM TB infrastructure to produce SAIF, then run PrimeTime PX in averaged mode over each SAIF to compute `power_mw`; self-judge the `power_mw` PPA dimension.

## When to Use

- First-time setup of the GLS power simulation + PT-PX averaged power-analysis environment.
- End-to-end run: bootstrap (deploys the fresh workdir; aborts if already deployed) → `make all` (tb-shim + refresh-tests → gls-compile → gls-run → ptpx) → write `result.json`.
- Re-run after a dependency artifact change: any change to the synthesized netlist / SDF / `power_scenarios[]` / TB infrastructure.
- Multi-scenario sweep: per-scenario SAIF per `power_scenarios[]` entry, each with its own `reports_ptpx/<id>/`.

## Iron Rule

- The injected read-only input locations `<netlist>`/`<tb_env>`/`<scaffold>`/`<ppa>` — never modify them; write only under `{workdir}`.
- Power test classes (`power_<seq>_test.sv`) are **auto-generated** by this stage — do not hand-write them or reuse power tests from any other source. Internally, each test reuses the `{module}_<seq>_seq` class already compiled by simulation (the plan's `power_scenarios[].sequence_ref` and `sequences[].name` share a namespace); this stage does NOT render an independent sequence class (contract violation — multi-source power tests cause naming / semantic drift).
- The TB emits SAIF directly via `$set_gate_level_monitoring + $toggle_*` — `$dumpfile / $dumpvars` are **forbidden** (architectural violation — the SAIF path does not go through VCD; direct toggle dump avoids intermediate-format loss).
- `ptpx.tcl` locks `power_analysis_mode averaged` + `read_saif`.
- On failure, `failures[].{phase, category, error_summary}` MUST be filled in (contract violation — missing categorization makes the root cause unidentifiable).
- `hier_separator` MUST be explicitly set to `"/"` at the top of `ptpx.tcl`: write both `catch {set_app_var hier_separator "/"}` + `set hier_separator "/"` — PT M-2016 treats this as a Tcl global (`set_app_var` reports CMD-104), while newer PT treats it as an application var; the default dot-separated value causes `strip_path` to silently mismatch (contract violation — power hierarchy paths become unresolvable).
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{directive_path}` | Optional on any dispatch. Fix-scope hint file; when present, Read it first. |

### External reference inputs

Each read-only upstream input's location is injected — read `inputs.json` in your `{workdir}`; below, `<key>` denotes that input's location, so you read `<key>/<subpath>`.

| Path | Schema / Format | Use |
|---|---|---|
| `<tb_env>/filelist.f` | UVM filelist | TB infrastructure compile list (read-only). |
| `<tb_env>/tb/uvm/**/*.sv` | UVM SystemVerilog | TB infrastructure, referenced by `filelist.f` (read indirectly). |
| `<scaffold>/scaffold-specification.json` | simulation-plan schema | `power_scenarios[]` list (drives `emit_power_tests` + `run_gls_power`). |
| `<netlist>/out/<TOP>_syn.v` | structural Verilog | Synthesized netlist (VCS GLS compile + PT-PX `read_verilog`). |
| `<netlist>/out/<TOP>_syn.sdc` | SDC | PT-PX `read_sdc` (constraint propagation). |
| `<netlist>/out/<TOP>_syn.sdf` | SDF v3.0 | VCS SDF back-annotation delay + PT-PX `read_sdf` (state-dependent leakage). |
| `LIB_V` (env) | std cell Verilog model path | linked against the netlist at VCS compile time. |
| `LIB_DB` (env) | std cell Liberty `.db`/`.lib` | PT-PX activity→power mapping (MUST match what was used at synthesis). |
| `UVM_HOME` (env) | UVM library path | matches what TB infrastructure was built against. |

PPA targets (entries on the `power_mw` dimension only) are read by `power finalize` itself from the injected `ppa` location (`inputs.json`) — nothing is injected in the prompt.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope.schema.json | This stage's status contract (includes `saif_artifacts[]` / `compile_info` / `failures[]` / `ppa_actual[]` / `violations[]` / `power_by_corner[]`). |
| `saif/<id>.saif` (+ `saif/_dedup/<sequence_ref>.saif`) | SAIF | Per-scenario gate-level SAIF (dedup-hardlinked); each path referenced by `result.json.saif_artifacts[]`. |
| `reports_ptpx/<id>/` (`power_hier.rpt` / `power_flat.rpt` / `switching_activity.rpt` / `ptpx.log`) | PT text + log | Per-scenario PT-PX report set (`power_hier.rpt` is read by rtl-design on a PPA rework); one `<id>/` per SAIF. |

The promoted full set (the deployed `scripts/` + `scaffold/` infrastructure, `simv` + `simv.daidir/`,
the `gls-compile-log.txt` / `gls-run-log.txt` / `ptpx.log` / `make.out` logs, and `power-actual.json`)
is enumerated by `power finalize` — this table is the contract surface, not a mirror of it. The
deployed infrastructure is `bootstrap`'s business (Step 2; per-file notes in Bundled References);
you interact with it only through the `make` targets.

## Workflow

`{workdir}` is provided empty each dispatch; bootstrap deploys it (and aborts on a within-run re-entry where a `Makefile` already exists). `make refresh-tests` re-renders power tests from the current plan before every `gls-compile`.

### Step 1: Pre-check external references

Confirm `<tb_env>/filelist.f` / `<scaffold>/scaffold-specification.json` (non-empty `power_scenarios[]`) / the synthesis trio (`<netlist>/out/<TOP>_syn.{v,sdc,sdf}`) present AND `LIB_V`/`LIB_DB`/`UVM_HOME` set with valid paths. On any miss, write `status=fail` + `failure_kind="infra"` + `fail_reason="external reference missing: <path>"` and exit. When `{directive_path}` is injected, Read it first as a fix-scope hint.

### Step 2: Bootstrap

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/power/__main__.py bootstrap --module {module} --workdir {workdir} [--top <TOP>]
```

Copies `templates/`, substitutes placeholders, renders power tests. Aborts if a `Makefile` is already deployed (incremental updates go through `make refresh-tests`).

### Step 3: Run and judge

`cd {workdir} && make all >make.out 2>&1` (redirect keeps the multi-thousand-line VCS/PT logs out of context; each stage still tees to its own log file).

- **`make` exited non-zero** → read a **bounded** slice of the failing stage's log (`gls-compile-log.txt` / `gls-run-log.txt` / `ptpx.log`) — never the whole dump. Determine the failure's **`category`**:
  1. If a `make` step already printed `phase=<p> category=<x>` (SDF-0 → `phase=compile`/`category=sdf`; `SAIF empty` → `phase=run`/`category=saif_dump`; `annotated 0%` → `phase=ptpx`/`category=ptpx_data`; PT design-load → `phase=ptpx`/`category=netlist`|`sdf`), **copy both verbatim**.
  2. Otherwise (a VCS compile error → all `phase=compile`) classify by the **named file's directory**:

  | error names a file under… | category |
  |---|---|
  | `<netlist>/out/*.v` | `netlist` |
  | `<netlist>/out/*.sdf` | `sdf` |
  | TB filelist roots (`<tb_env>/...`) or local `power_filelist.f` | `tb_uvm` |
  | no named file / VCS flag / `UVM_HOME` / license error | `tooling` |

  Write `status=fail` + `failure_kind` (`infra` for missing-reference/license; else `tooling`) + `failures[].{phase, category, error_summary}` + `fail_reason`. **Write only the failure facts (`phase` / `category`); do NOT assign any rework or routing target — target selection is owned downstream, outside this stage.**

- **`make` exited 0** → run the parser's finalize subcommand; do not run the parser separately, fold `power-actual.json` by hand, or hand-assemble the envelope:

  ```bash
  python3 ${CLAUDE_SKILL_DIR}/scripts/power/__main__.py finalize \
    --workdir {workdir} --module <module> \
    --scaffold <scaffold>/scaffold-specification.json
  ```

  `finalize` reuses the parser's PT-PX gate (parses each `reports_ptpx/<id>/power_flat.rpt`, checks the Total = internal+switching+leakage invariant, judges the `power_mw` PPA dimension against the targets it reads itself from the injected `ppa` location (`inputs.json`) — an absent file skips the gate), writes `power-actual.json`, folds its `stage_specific` fields through, enumerates `artifacts[]`, and writes the complete `result.json`. Exit 0 = result.json written (status pass or fail). A non-zero finalize exit is a program exception (BLOCKED), not a `status=fail`.

  `failure_kind` is set by finalize (see `references/result.schema.json` `failure_kind` enum/description); `infra` (external reference / license missing) is written by the Step-1 pre-check before finalize runs, and on the `make`-non-zero VCS-compile triage above you also write the `failures[]`/`failure_kind` directly (the gate never runs there).

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
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] result.json was written by the `power` CLI's `finalize` verb (it owns status / the 7 stage_specific fields / artifacts / failure_kind).
- [ ] Every `saif_artifacts[].saif_path` file exists and `size > 0`.
- [ ] Every `reports_ptpx/<id>/{power_hier.rpt, power_flat.rpt, switching_activity.rpt, ptpx.log}` is present.
- [ ] `gls-compile-log.txt` and `gls-run-log.txt` are on disk.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`templates/Makefile`](templates/Makefile) — `gls-compile` + `gls-run` + `ptpx` + `all` entry point.
- `templates/scripts/emit_power_tests.py` — power test template renderer (make-internal).
- `templates/scripts/build_tb_filelist_abs.py` — absolute-path rewrite of the simulation filelist (consumed across stages by GLS; make-internal).
- `templates/scripts/run_gls_power.sh` — per-scenario `simv` dispatch (dedup via hardlink; make-internal).
- `templates/scripts/ptpx.tcl` — PT-PX averaged main script (`read_saif` + 0% annotation hard gate; make-internal).
- [`templates/scaffold/power_test.sv.tmpl`](templates/scaffold/power_test.sv.tmpl) — UVM test template (placeholders `MODULE` / `AGENT_NAME` / `SEQUENCE_REF` / `TOP` / `SCENARIO_ID` / `SCENARIO_DESC` / `DURATION_CYCLES`; contains `$set_gate_level_monitoring + $toggle_*`).
- `scripts/power/__main__.py bootstrap` — bootstrap verb (invocation contract: Step 2 + `--help`).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- `scripts/power/__main__.py finalize` — PT-PX report parser + PPA verdict verb (assembles `power-actual.json` then result.json; exit code is the pass/fail truth — mirrors the `synthesis` CLI's `finalize`; invocation contract: Step 3 + `--help`).
- [`${CLAUDE_PLUGIN_ROOT}/skills/simulation-plan/references/power-scenarios-template.md`](../simulation-plan/references/power-scenarios-template.md) — `power_scenarios` field semantics.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
