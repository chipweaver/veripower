---
name: timing-analysis
description: Use when running static timing analysis on synthesis netlist, analyzing setup/hold violations, reviewing timing reports, or re-analyzing after synthesis changes; not for synthesis or power analysis.
---

# Static Timing Analysis

This skill's sole responsibility: run independent PrimeTime STA on the post-synthesis netlist, classify setup / hold path-level violations, and self-judge the `timing_setup` / `timing_hold` dimensions via `timing_rpt_parser.py` — never by eye.

## When to Use

- Synthesis has completed and an independent STA verification is needed.
- Analyze setup / hold violations.
- Re-analyze timing after the post-synthesis netlist or constraints change.
- Confirm whether timing meets signoff accuracy.

## Iron Rule

- Do not modify any file under `Design/synthesis/`. Synthesis products (netlist / SDC) are read-only external references.
- An independent STA tool (PrimeTime) MUST be used, not the synthesis tool's built-in timing engine (contract violation — the in-synthesis engine uses estimated delays and cannot meet signoff accuracy).
- When no PT license is available, write `status=fail` + `failure_kind="infra"` + `fail_reason="PT license missing"`; do not claim STA is complete.
- If synthesis products (netlist / SDC) do not exist, write `status=fail` + `failure_kind="infra"` + `fail_reason="external reference missing: <path>"`; do not bypass.
- `timing-report.txt` MUST be written to disk; claiming STA complete without it is not allowed.
- Classify on the report's `(VIOLATED)` / `(MET)` marker — never on the displayed slack number (a sub-rounding violation prints `0.00`). The parser owns this; do not hand-classify.
- Scripts are black boxes — never Read their source. Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |

This stage never receives a `{rework_trigger}` injection (it is not itself a valid fix target); only `{workdir}` / `{module}` are delivered. (See the Workflow rationale.)

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

Confirm `Design/synthesis/result.json` exists and `status=pass`, and `Design/synthesis/out/<TOP>_syn.{v,sdc}` are present. If `result.json` is missing or `status≠pass` → write `status=fail`, `failure_kind="infra"`, `fail_reason="external reference not pass: Design/synthesis/result.json"` and exit; if the netlist/SDC are missing → `failure_kind="infra"`, `fail_reason="external reference missing: <path>"` and exit.

### Step 2: Bootstrap

`bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap_timing_analysis.sh --module {module} --workdir {workdir}`. Deploys `run_sta.tcl` + `config.tcl`, resolves `<TOP>`, verifies the netlist/SDC, and aborts if `{workdir}` is already deployed.

### Step 3: Set `LIB_DB`

(`export LIB_DB=<path-to-slow.db>` — the same `.db` as synthesis — or edit `{workdir}/config.tcl`) and **run STA from the workdir** so PrimeTime's auto-logs (`pt_shell_command.log`, `.svf`) land inside the gitignored workdir, not the tree root: `cd {workdir} && pt_shell -f run_sta.tcl`. The TCL uses absolute paths (set by bootstrap) and its `redirect` writes `{workdir}/timing-report.txt`.

### Step 4: Run the parser

(mandatory; do not classify by hand): `python3 ${CLAUDE_SKILL_DIR}/scripts/timing_rpt_parser.py --report {workdir}/timing-report.txt --out {workdir}/timing-actual.json`.
- **On exit 0**, read `{workdir}/timing-actual.json` and fold it in: `timing` → `stage_specific.timing`, `violations` → `stage_specific.violations`, `verdict` → `status`. A `verdict="fail"` → `status=fail`, `failure_kind="ppa"`, plus a one-line `fail_reason` (e.g. `"setup/hold timing not met"`).
- **On a non-zero exit**, the parser is authoritative — never infer pass from the report's presence. Read its `FAIL=` token and write `status=fail`, `failure_kind="tooling"`, the matching `fail_reason` (`FAIL=missing` → `"timing-report.txt missing"`; `FAIL=unparseable` → `"timing-report.txt unparseable"`), then exit.

### Step 5: Write `{workdir}/result.json`

(schema: `references/result.schema.json` + envelope). When `status=pass`, `stage_specific.{timing, violations}` are required (`violations=[]`). When `status=fail`, `stage_specific.{fail_reason, failure_kind}` are required (`failure_kind ∈ {infra, tooling, ppa}`):
- `failure_kind="infra"`: external reference missing / not pass / PT license missing — PT did not run.
- `failure_kind="tooling"`: PT ran but errored, or the report was missing/unparseable (parser exit 1/3).
- `failure_kind="ppa"`: PT ran to completion but setup/hold not met — `timing{}` + `violations[]` carry the numbers.

**Workflow rationale — single linear flow.** This stage is a read-only re-verifier — it cannot modify the synthesis netlist/SDC or apply any fix, so every run does identical work and there is no first-run / incremental / re-run fork to branch on. Step 1 is a linear pre-flight check, not a branch; each run uses a fresh `{workdir}` (Step 2 aborts if one is already deployed). For why this stage carries no branch fork (and receives no `{rework_trigger}`), see the carve-out in `docs/skill-branch-routing-design.md` §6.6.

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
- [ ] Every artifact path is listed in `result.json.artifacts[]`.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] `result.json.status` written (`pass` or `fail`; the envelope does not accept `blocked`); on `fail`, `stage_specific.{fail_reason, failure_kind}` required.
- [ ] The gate ran via `timing_rpt_parser.py`: on `status=pass` / `failure_kind="ppa"`, its `timing-actual.json` (exit 0) was folded into `stage_specific.{timing, violations}`; on a non-zero parser exit, `failure_kind="tooling"` + matching `fail_reason`; on `failure_kind ∈ {infra, tooling}`, only `fail_reason` + `failure_kind` are needed (the parser did not run / produced no `timing-actual.json`).
- [ ] `{workdir}/run_sta.tcl`, `{workdir}/config.tcl`, and `{workdir}/timing-report.txt` exist on disk.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
