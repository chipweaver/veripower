---
name: timing-analysis
description: Use when running static timing analysis on synthesis netlist, analyzing setup/hold violations, reviewing timing reports, or re-analyzing after synthesis changes; not for synthesis or power analysis.
---

# Static Timing Analysis

Your sole responsibility: run independent PrimeTime STA on the post-synthesis netlist, classify setup / hold path-level violations, and self-judge the `timing_setup` / `timing_hold` dimensions via the `timing` CLI's `finalize` verb — never by eye.

## When to Use

- Synthesis has completed and an independent STA verification is needed.
- Analyze setup / hold violations.
- Re-analyze timing after the post-synthesis netlist or constraints change.
- Confirm whether timing meets signoff accuracy.

## Iron Rule

- Do not modify any file under `Design/synthesis/`. Synthesis products (netlist / SDC) are read-only external references.
- An independent STA tool (PrimeTime) MUST be used, not the synthesis tool's built-in timing engine (contract violation — the in-synthesis engine uses estimated delays and cannot meet signoff accuracy).
- When no PT license is available, write `status=fail` + `fail_reason="PT license missing"`; do not claim STA is complete.
- If synthesis products (netlist / SDC) do not exist, write `status=fail` + `fail_reason="external reference missing: <path>"`; do not bypass.
- `timing-report.txt` MUST be written to disk; claiming STA complete without it is not allowed.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |

Only `{workdir}` / `{module}` are delivered. (See the Workflow rationale.)

### External reference inputs

| Path | Schema / Format | Required | Use |
|---|---|---|---|
| `Design/synthesis/result.json` | `skills/synthesis/references/result.schema.json` | required | Prerequisite `status=pass`. |
| `Design/synthesis/out/<TOP>_syn.v` | Verilog gate-level netlist | required | STA input netlist. |
| `Design/synthesis/out/<TOP>_syn.sdc` | SDC | required | Post-synthesis constraints. |

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope.schema.json | Status contract (`stage_specific.timing{}` + `violations[]`). |
| `run_sta.tcl` / `config.tcl` | Tcl | STA script + config (deployed by bootstrap). |
| `timing-report.txt` | PrimeTime text report | setup / hold / check_timing output (the deliverable). |
| `timing-actual.json` | JSON (`verdict` + `timing` + `violations`) | Parser output (Step 4 folds it into `result.json`). List in `artifacts[]` when present. |

## Workflow

This is a single linear flow (no branch fork — see rationale below).

### Step 1: Pre-check external references

Confirm `Design/synthesis/result.json` exists and `status=pass`, and `Design/synthesis/out/<TOP>_syn.{v,sdc}` are present. If `result.json` is missing or `status≠pass`, write `status=fail`, `failure_kind="infra"`, `fail_reason="external reference not pass: Design/synthesis/result.json"` and exit; if the netlist/SDC are missing, write `failure_kind="infra"`, `fail_reason="external reference missing: <path>"` and exit.

### Step 2: Bootstrap

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/timing/__main__.py bootstrap --module {module} --workdir {workdir}
```

Deploys `run_sta.tcl` + `config.tcl`, resolves `<TOP>`, verifies the netlist/SDC, and aborts if `{workdir}` is already deployed.

### Step 3: Set `LIB_DB`

(`export LIB_DB=<path-to-slow.db>` — the same `.db` as synthesis — or edit `{workdir}/config.tcl`) and **run STA from the workdir** so PrimeTime's auto-logs (`pt_shell_command.log`, `.svf`) land inside the gitignored workdir, not the tree root:

```bash
cd {workdir} && pt_shell -f run_sta.tcl
```

The TCL uses absolute paths (set by bootstrap) and its `redirect` writes `{workdir}/timing-report.txt`.

### Step 4: Build `{workdir}/result.json` (mandatory)

Run the parser's finalize subcommand; do not run the parser separately, fold `timing-actual.json` by hand, or hand-assemble the envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/timing/__main__.py finalize \
  --workdir {workdir} --module <module> --top <top_module>
```

`finalize` reuses the parser's timing gate (classifies each direction on the report's `(MET)`/`(VIOLATED)` marker — never the displayed number — and judges pass = setup MET and hold MET), writes `timing-actual.json`, derives the reproducibility header (tool from the report `Version:` line / lib_db from `config.tcl` / clock from the synthesis SDC), enumerates `artifacts[]`, and writes the complete `result.json`. Exit 0 = result.json written (status pass or fail). A non-zero finalize exit is a program exception (BLOCKED), not a `status=fail`.

`failure_kind` is set by finalize (see `references/result.schema.json` `failure_kind` enum/description); you write `failure_kind=infra` in the Step-1 pre-check (PT never ran — external ref / license missing) before finalize runs.

**Workflow rationale — single linear flow.** You are a read-only re-verifier — you cannot modify the synthesis netlist/SDC or apply any fix, so every run does identical work and there is no first-run / incremental / re-run fork to branch on. Step 1 is a linear pre-flight check, not a branch; each run uses a fresh `{workdir}` (Step 2 aborts if one is already deployed). You therefore carry no branch fork and receive no `{rework_trigger}`.

## Red Flags

| Excuse | Reality |
|---|---|
| "slack reads 0.00 — that's met" | Classify on the `(VIOLATED)` / `(MET)` **marker**, never the number: PrimeTime prints a real sub-rounding violation as `0.00`. The parser keys on the marker; do not override it. |
| "Setup is clean — mark pass" | The parser checks `timing_setup` **and** `timing_hold`; any direction with a `(VIOLATED)` marker → `status=fail`. Skipping hold is impossible — `run_sta.tcl` always runs `-delay max` and `-delay min`. |
| "STA ran and the report is there — mark pass" when the parser exited non-zero | A non-zero parser exit is authoritative: `FAIL=missing`/`FAIL=unparseable` → `status=fail` + `failure_kind="tooling"`. Report presence is not a met gate. |

## Pitfalls

| Mistake | Fix |
|---|---|
| SDC constraints out of sync with synthesis | The TCL reads `Design/synthesis/out/<TOP>_syn.sdc` (exported from synthesis); never rewrite by hand. |
| Editing `run_sta.tcl` by hand per run | The bootstrap deploys the vetted template; re-bootstrap a fresh `runs/N` rather than improvising flags. |

## Completion Gate

- [ ] `{workdir}/result.json` written and passes schema validation.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] `result.json.status` written (`pass` or `fail`; the envelope does not accept `blocked`); on `fail`, `stage_specific.{fail_reason, failure_kind}` required.
- [ ] result.json was written by the `timing` CLI's `finalize` verb (it owns status / timing / violations / artifacts / failure_kind / the reproducibility header).
- [ ] `{workdir}/run_sta.tcl`, `{workdir}/config.tcl`, and `{workdir}/timing-report.txt` exist on disk.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
