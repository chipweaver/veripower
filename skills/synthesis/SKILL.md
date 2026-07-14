---
name: synthesis
description: Use when running Design Compiler synthesis, analyzing timing/area/power reports, supplementing SDC exceptions, or re-synthesizing after RTL changes; not for power analysis or static timing.
---

# Synthesis

Your sole responsibility: run Design Compiler synthesis against the RTL filelist and the SDC source of truth, iteratively supplement SDC timing exceptions, and self-judge the area_um2 / timing_slack_ns PPA dimensions.

## When to Use

- First-time setup of the DC synthesis environment.
- Run synthesis (`make synthesis`).
- Analyze timing / area reports.
- Supplement SDC timing exceptions (false path / multicycle path / generated clock).
- Re-synthesize after RTL changes.

## Iron Rule

- Do not modify any file under `Design/rtl-design/` or `Design/specification/` — these are read-only external references for synthesis.
- Timing exceptions MUST be supplemented iteratively after RTL becomes visible; they cannot be pre-written at the specification stage (contract violation — RTL port names cannot be known in advance).
- Do not claim synthesis is complete when the DC license is missing — without a license, write `status=fail` + `fail_reason="DC license missing"`.
- Do not claim synthesis is complete when the netlist (`out/<TOP>_syn.v`) does not exist — the netlist must land on disk.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{failing_result}` | Optional. The failed stage's canonical `result.json` path (`stage_specific` shape per that stage's schema); when present, its `stage_specific.violations[]` supplies this round's fix scope (Step 1). |
| `{directive_path}` | Optional. Fix-scope hint file; Read it first — priority over the trigger content. |

### External reference inputs

| Path | Schema / Format | Use |
|---|---|---|
| `Design/rtl-design/filelist.txt` | text | RTL file list. |
| `Design/rtl-design/README.md` | Custom markdown | Constraint-annotation note (SDC: generated clock / multicycle / false path). |
| `Design/specification/constraints/<TOP>.sdc` | SDC | SDC source of truth (optional) — bootstrap seeds the working `constraints.sdc` from it, else the template placeholder. |
| `LIB_DB` (env) | std cell Liberty `.db` path | Set before any run (Step 3) — `env.sh` / Makefile fail loudly when unset. |

When `{failing_result}` is injected, read additional context from the same directory as the trigger file; field names come from the triggering stage's own `result.schema.json` (e.g. `failures[].{phase, category, error_summary}`), and the content drives the fix scope for this round — the specific read scope is not enumerated ahead of time. PPA targets (`area_um2` / `timing_slack_ns` dimensions) are read by `synthesis finalize` itself from `Design/specification/ppa.json` — nothing is injected in the prompt.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope.schema.json | This stage's status contract (`stage_specific.ppa_actual[]` + `violations[]` on failure; netlist / SDC / SDF paths go in envelope `artifacts[]`). |
| `out/<TOP>_syn.v` | Verilog | Synthesized gate-level netlist (consumed by timing-analysis + power-analysis). |
| `out/<TOP>_syn.sdc` | SDC | Post-synthesis SDC (consumed by timing-analysis + power-analysis). |
| `out/<TOP>_syn.sdf` | SDF v3.0 | SDF back-annotation file, includes state-dependent leakage data (consumed by power-analysis). |
| `reports/qor.rpt` / `area.rpt` / `timing_setup.rpt` / `timing_hold.rpt` / `power.rpt` / `check_design.rpt` | text reports | DC synthesis report set (read by rtl-design during a PPA rework). |
| `constraints.sdc` | SDC | Timing-exception iteration site, edited by you (Steps 4/6). |
| `scripts/config.tcl` | TCL | Edit to fill `LIB_DB` (Step 3 alternative to the env var). |

The promoted full set (including `ppa-actual.json`, `run.log`, and the remaining deployed scripts) is enumerated by `synthesis finalize` — this table is the contract surface, not a mirror of it.

## Workflow

### Step 1: Read inputs and determine scope

Pre-check the external references: `Design/rtl-design/filelist.txt` (containing ≥1 RTL entry — not a comment, not a `+` / `-` directive) and `README.md` all present. If any file is missing, write `status=fail` + `fail_reason="external reference missing: <path>"` and exit; if filelist exists but has no usable RTL entries, write `fail_reason="external reference missing: Design/rtl-design/filelist.txt (no RTL entries)"` and exit.

Determine this round's fix scope from the first available source:
1. `{directive_path}`'s `fix_locus` when injected — Read that sibling file first; authoritative.
2. Else, on a `{failing_result}`, its `stage_specific.violations[]` — if the trigger is unreadable, write `result.json` with `status=fail` + `stage_specific.fail_reason="failing_result not readable"` and exit.
3. Else, if `{workdir}/changed-inputs.md` is present, it lists the input files that changed since this stage's last run — confine the Step 4/6 SDC / timing-exception edits to them. If it is absent or empty but a prior run was promoted (a re-verify), keep the scope empty — the synthesis run and PPA self-check (Steps 5/7/8) are unconditional regardless.
4. Else (a first delivery) the full flow.

**Scope confinement.** Steps 2–8 run in the same order regardless of scope and differ only in it: the SDC / timing-exception edits in Steps 4 and 6 stay confined to the scope set here. Steps 2–3 (bootstrap + `LIB_DB`) deploy the workdir — Step 2 aborts once `{workdir}` is already deployed, so a within-run re-entry is a no-op and any residue survives; Steps 5 / 7 / 8 (synthesis run, PPA self-check, `result.json` write) are unconditional.

### Step 2: Bootstrap

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/synthesis/__main__.py bootstrap --module {module} --workdir {workdir} [--top <TOP>]
```

Deploys the templates into `{workdir}`, generates `scripts/rtl_load.tcl` + `scripts/config.tcl`, and seeds `constraints.sdc`; aborts when `{workdir}` is already deployed. Mechanics — placeholder substitution, SDC source-of-truth, `+incdir+` handling, `LIB_DB`, `--top` inference — are documented once in `references/makefile-bootstrap.md`.

### Step 3: Fill in `LIB_DB`

`export LIB_DB=<path>` or edit `{workdir}/scripts/config.tcl` to replace `FILL_IN_LIB_DB_PATH`; `env.sh` and the Makefile both fail loudly when `LIB_DB` is unset.

### Step 4: Edit `{workdir}/constraints.sdc`

- Read the SDC portion of the "constraint-annotation note" in `Design/rtl-design/README.md`; add `create_generated_clock` entries (if any).
- Replace the `set_clock_uncertainty -setup` / `-hold` placeholder values with the values from the process library (when undocumented, keep setup=`0.2 ns` / hold=`0.0 ns` and add a note; pre-CTS hold = 0 — see `specification/references/sdc-template.md`).
- Fill `set_drive` / `set_load` per the IO cell library (when there is no spec, keep the placeholders and add a note).
- Confirm `set_input_delay` / `set_output_delay` (replace from the interface spec when available).

### Step 5: First synthesis run

`make synthesis` runs `dc_shell` and can outrun the foreground Bash timeout. Launch it as one
detached background job (`run_in_background=True`) from `{workdir}` (the Makefile tees `run.log`),
then end your turn and wait for the harness completion notification. On wake, read `run.log` once
(tail + exit status) and proceed. Never foreground the run — the result never returns synchronously,
which forces token-burning hand-rolled waiting; never poll with `sleep` / `pgrep` / `until … done`
(nor background such a loop) nor re-read the growing `run.log` across turns; do not emit `STATUS`
until `result.json` is written.

### Step 6: Iteratively supplement timing exceptions

Extract the violated paths from `reports/timing_setup.rpt`, keeping each path's startpoint / endpoint / slack (the file/line/cause needed to classify it; e.g. `grep -B2 -A25 -i "violated" reports/timing_setup.rpt`, widening the window when a path needs deeper inspection).
- Known multicycle paths → add `set_multicycle_path`.
- Known static false paths → add `set_false_path`.
- Re-run `make synthesis` (same detached-background protocol as Step 5); repeat until the remaining violations are real timing issues or have been excepted.

### Step 7: Build `{workdir}/result.json` (mandatory)

Run the parser's finalize subcommand; do not hand-assemble the envelope or extract/compare by hand. It reads the PPA targets itself from `Design/specification/ppa.json` (dims `area_um2` / `timing_slack_ns` only; `power_mw` is judged downstream; an absent file or dim leaves that dimension ungated) — you pass no target flags:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/synthesis/__main__.py finalize \
  --workdir {workdir} --module <module> --top <top_module>
```

`finalize` reuses the parser's PPA gate (worst setup slack = `min` of `Critical Path Slack` across all clock-group blocks; area = `Total cell area`) against the `Design/specification/ppa.json` targets, derives the reproducibility header (tool / lib_db / clock / ppa_targets), enumerates `artifacts[]`, and writes the complete `result.json`. Exit 0 = result.json written (status pass or fail). A non-zero finalize exit is a program exception (BLOCKED), not a `status=fail`.

`failure_kind` is set by finalize (see `references/result.schema.json` `failure_kind` enum/description); you write `failure_kind=infra` on the pre-checks of Steps 1–5 (DC never ran — external ref / license / trigger) before finalize runs.

## Decision Rules

- Interface spec missing → keep the placeholder values and add a `# notes:` comment; do not guess port names.
- Timing violation cannot be classified (neither known multicycle nor known false path) → `status=fail`, record it in `violations[]`.

## Red Flags

| Excuse | Reality |
|---|---|
| "Synthesis ran and the netlist is there — mark pass" when `synthesis finalize` exited non-zero | A non-zero parser exit is authoritative: read its `FAIL=` token and write `status=fail` + `failure_kind="tooling"`. Artifact presence is not a met gate — the parser owns extraction and the area/slack comparison. |

## Pitfalls

| Mistake | Fix |
|------|------|
| `rtl_load.tcl` out of sync with `filelist.txt` | After RTL changes, regenerate `rtl_load.tcl`. |
| `set_clock_uncertainty` uses placeholder values without a note / collapses back to the single-value form | Placeholder values must be flagged in `constraints.sdc` with a `# notes:` comment for later replacement; keep the `-setup` / `-hold` split (pre-CTS hold = 0); do not merge them back into a single value. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written and passes schema validation.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] The `result.json.status` decision has been written (`pass` or `fail`; the envelope does not accept blocked); on `fail`, `stage_specific.{fail_reason, failure_kind}` are required.
- [ ] result.json was written by `synthesis finalize` (it owns status / ppa_actual / artifacts / failure_kind / the reproducibility header).
- [ ] `scripts/rtl_load.tcl` matches `Design/rtl-design/filelist.txt`.
- [ ] `create_generated_clock` covers every generated clock in the RTL (or the SDC remarks in `Design/rtl-design/README.md` confirm there are none).
- [ ] `set_false_path` / `set_multicycle_path` cover the exception paths annotated in the RTL `README.md`.
- [ ] Remaining timing violations have been classified (real violations have been recorded in `violations[]`).
- [ ] `out/<TOP>_syn.v` / `out/<TOP>_syn.sdc` / `out/<TOP>_syn.sdf` exist.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`references/makefile-bootstrap.md`](references/makefile-bootstrap.md) — Bootstrap and Makefile target quick reference.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
