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

- The injected input locations (`<rtl>`, `<annotations>`, `<sdc>`, `<ppa>` — from `dispatch.json`) are read-only canonical: never modify anything under them (or any other stage's canonical output); the only files you write live under `{workdir}`.
- Timing exceptions MUST be supplemented iteratively after RTL becomes visible; they cannot be pre-written at the specification stage (contract violation — RTL port names cannot be known in advance).
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |

### External reference inputs

Read `{workdir}/dispatch.json`: its `inputs` table maps each read-only upstream input to its location, so `<key>` below denotes that location and you read `<key>/<subpath>`.

| Path | Schema / Format | Use |
|---|---|---|
| `<rtl>/rtl-files.json` | `skills/rtl-design/references/rtl-files.schema.json` | Per-child RTL file layout; the bootstrap generates `scripts/rtl_load.tcl` from it. |
| `<annotations>/constraint-annotations.json` | `skills/rtl-design/references/constraint-annotations.schema.json` | Per-child SDC annotations (`create_generated_clock` / `set_multicycle_path` / `set_false_path`). |
| `<sdc>/constraints/<TOP>.sdc` | SDC | SDC source of truth — bootstrap copies it to the working `constraints.sdc`. Required: it is what makes the timing numbers mean anything, so bootstrap fails closed without it rather than deploying a template that would constrain a clock port the design does not have. |
| `LIB_DB` (env) | std cell Liberty `.db` path | Set before any run (Step 3) — `env.sh` / Makefile fail loudly when unset. |

When `dispatch.json` carries a `caused_by`, read each envelope it names and the additional context in that envelope's own directory; field names come from the failing stage's `result.schema.json` (e.g. `failures[].{phase, error_summary}`), and the content drives the fix scope for this round — the specific read scope is not enumerated ahead of time. PPA targets (`area_um2` / `timing_slack_ns` dimensions) are read by `synthesis finalize` itself from the injected `ppa` location — nothing is injected in the prompt.

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

`constraints.sdc` is carried into a fresh workdir from the previous round before you start, so
it may already hold converged timing exceptions and documented library values when you open it.
Treat what is there as work you inherited, not as the specification SDC: exceptions are written
against RTL port names, so re-deriving a set you already have costs a full re-synthesis per
round. Re-check each inherited exception against this run's reports, and delete one whose path
no longer exists.

## Workflow

### Step 1: Determine scope

`{workdir}/dispatch.json` narrows this round when it carries either key, and the scope is the
union of both: `scope` names module-relative paths or `<file>:<line>` anchors that changed since
this stage's last run, and `caused_by` names the `result.json` of each upstream failure this
round answers, whose `stage_specific.violations[]` say what missed. Confine the Step 4/6 SDC
edits to what they name. With neither, nothing is narrowed. Steps 2–7 are mechanically identical
either way, because dc_shell synthesizes the whole design regardless.

### Step 2: Bootstrap

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/synthesis/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

It deploys the templates into `{workdir}`, copies `<sdc>/constraints/<TOP>.sdc` to `constraints.sdc` verbatim, and generates `scripts/rtl_load.tcl` (the `analyze` list, plus each child's `incdirs[]` on `search_path`) and `scripts/config.tcl` from the rtl-design file layout. It aborts when `{workdir}/Makefile` already exists (the kernel-written `dispatch.json` does not count as "deployed"), and when `--top` is omitted it reads the name from `manifest.module`. Non-zero exit: stderr names the cause.

The deployed `Makefile`, `env.sh`, `scripts/dc_run.tcl` and `scripts/rtl_load.tcl` are make-internal. `make synthesis` is the interface; the only deployed files you edit are `constraints.sdc` and `scripts/config.tcl`.

### Step 3: Fill in `LIB_DB`

`export LIB_DB=<path>` or edit `{workdir}/scripts/config.tcl` to replace `FILL_IN_LIB_DB_PATH`; `env.sh` and the Makefile both fail loudly when `LIB_DB` is unset.

### Step 4: Edit `{workdir}/constraints.sdc`

- Read `<annotations>/constraint-annotations.json` and union the `sdc` block across every child; add a `create_generated_clock` for each `{module, pin}` entry (if any).
- Replace the `set_clock_uncertainty -setup` / `-hold` placeholder values with the values from the process library (each carries its own `;#` note in the generated file; when undocumented, keep setup=`0.2 ns` / hold=`0.0 ns` and add a note — pre-CTS hold = 0, and a single value for both would read every pre-CTS path as hold-VIOLATED).
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

### Naming the fix owner

Whenever you close a run with `status=fail`, name the rule whose artifact must change and pass it
as `--fix-owner <rule>` in Step 7, which is what puts it in `stage_specific.fix_owner`. This holds
for a license or tool failure exactly as much as for a PPA miss: a `fail_reason` that names the
guilty stage in prose while the flag was omitted reads to the caller as "this stage could not
tell", and brings a human in to re-derive an answer you already had.

A PPA gate compares a measured value against a target, and either side can be wrong. Before you
pass `--fix-owner rtl-design`, read `<ppa>/ppa.json` and check the target itself is well formed:
a `dim` whose unit disagrees with the number stored in it (an `area_um2` target holding a NAND2
gate count, say) makes a conforming design look over-budget, and rebuilding correct RTL against it
cannot converge. When the target is what is malformed, name `specification`. Omit the flag only
when you have read both sides and still cannot name an owner at all.

### Step 7: Write `{workdir}/result.json` (mandatory)

Run `finalize` to write the envelope. Every run closes here, including a `make` that never
reached the reports, and you never hand-assemble it or compare against a target by hand. It reads
the PPA targets itself from the injected `ppa` location (dims `area_um2` / `timing_slack_ns` only;
`power_mw` is judged downstream; an absent file or dim leaves that dimension ungated), so you pass
no target flags:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/synthesis/__main__.py finalize \
  --workdir {workdir} --module <module> [--fix-owner <rule>] \
  [--fail-reason "<cause>" --failure-kind {infra|tooling}]
```

It reuses the parser's PPA gate (worst setup slack = `min` of `Critical Path Slack` across all
clock-group blocks; area = `Total cell area`), derives the reproducibility header
(tool / lib_db / clock / ppa_targets), enumerates `artifacts[]`, and writes the complete
`result.json`. A clean gate is not enough for a pass: it also requires all three of
`out/*_syn.{v,sdc,sdf}` on disk, and reports an incomplete set as a `tooling` fail rather than
promoting a synthesis the downstream stages cannot read.

The two failure flags carry what the reports cannot. Pass them when dc_shell produced nothing
gradeable — no license, an `analyze` / `elaborate` / `link` / `check_design` / `compile` abort, a
crash after the reports landed — because you are the one who read `run.log`. `--fail-reason` is
itself the declaration of failure, so it wins over the gate and forces `status=fail` even where
the reports parse clean; pass it only when the run really failed, and write the cause you actually
read rather than a category (nothing parses the string). `--failure-kind` splits the one thing an
absent report cannot tell you apart: `infra` when DC never ran, `tooling` when it ran and its
output is unusable. `ppa` is the gate's to write, never yours.

Exit 0 = `result.json` written, whether the status is pass or fail. Exit 2 is BLOCKED, never a
`status=fail`: an empty `--fail-reason`, one without a `--failure-kind`, or a program exception.
stderr names which.

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
| `rtl_load.tcl` out of sync with `<rtl>/rtl-files.json` | After RTL changes, regenerate `rtl_load.tcl`. |
| `set_clock_uncertainty` uses placeholder values without a note / collapses back to the single-value form | Placeholder values must be flagged in `constraints.sdc` with a `# notes:` comment for later replacement; keep the `-setup` / `-hold` split (pre-CTS hold = 0); do not merge them back into a single value. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written and passes schema validation.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] The `result.json.status` decision has been written (`pass` or `fail`; the envelope does not accept blocked); on `fail`, `stage_specific.{fail_reason, failure_kind}` are required.
- [ ] result.json was written by `synthesis finalize` (it owns status / ppa_actual / artifacts / failure_kind / the reproducibility header, and matches the netlist trio by glob rather than by a name you pass).
- [ ] `scripts/rtl_load.tcl` matches `<rtl>/rtl-files.json`.
- [ ] `create_generated_clock` covers every `sdc.create_generated_clock` entry in `<annotations>/constraint-annotations.json` (every child reporting `[]` means there are none).
- [ ] `set_false_path` / `set_multicycle_path` cover the exception paths that file annotates.
- [ ] Remaining timing violations have been classified (real violations have been recorded in `violations[]`).
- [ ] `out/<TOP>_syn.v` / `out/<TOP>_syn.sdc` / `out/<TOP>_syn.sdf` exist.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
