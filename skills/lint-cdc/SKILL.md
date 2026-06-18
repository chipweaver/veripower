---
name: lint-cdc
description: Use when running SpyGlass lint or CDC checks, analyzing violations, adding waivers, supplementing SGDC annotations, or re-running after RTL changes; not for synthesis or simulation.
---

# Lint / CDC

This skill's sole responsibility: run SpyGlass lint / CDC against the RTL and the SGDC source of truth, iterate on depth annotations to suppress false positives, write the real violations into `result.json`, and persist the SGDC with the newly added depth annotations to lint-cdc's own canonical path (`Design/lint-cdc/scripts/constraints.sgdc`) for the next run's warm-start.

## When to Use

- First-time bring-up of the SpyGlass lint / CDC environment.
- Run a lint or CDC check.
- Analyze violations and add waivers.
- Re-run lint / CDC after an RTL change.
- Supplement SGDC depth annotations (`sync_cell` / `reset_synchronizer` / `set_case_analysis` / `quasi_static`).

## Iron Rule

- Do not modify the read-only external references — `Design/rtl-design/filelist.txt`, `Design/specification/design.md`, or `Design/specification/constraints/<TOP>.{sdc,sgdc}`. SGDC depth annotations belong to this stage's own canonical (`Design/lint-cdc/scripts/constraints.sgdc`); iterate only there, never write back to the spec source of truth.
- `{workdir}/scripts/constraints.sgdc` MUST be listed in `result.json.artifacts[]` — it then lands at the canonical path and the next bootstrap warm-starts from it; without that entry the file is not promoted and depth annotations must re-converge from scratch.
- Do not start when `Design/rtl-design/result.json.status≠pass` — write `status=fail` with `fail_reason="external reference not pass: Design/rtl-design/result.json"` and exit.
- Scripts are black boxes — never Read their source. Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{rework_trigger}` | Optional. Caller-injected trigger-context file path; contains `stage_specific.violations[]` and related context for this rework round. Its presence distinguishes the rework branch from the first-run and incremental-update branches. |
| `{orchestrator_context_path}` | Optional. Caller-injected fix-scope hint file path. When present, narrows the modification scope more precisely than `{rework_trigger}.violations[]` alone. |

### External reference inputs

| Path | Schema / Format | Required | Use |
|---|---|---|---|
| `Design/rtl-design/result.json` | `skills/rtl-design/references/result.schema.json` | required (first-run) | envelope (upstream status confirmation). |
| `Design/rtl-design/filelist.txt` | text | required (first-run) | RTL file list. |
| `Design/rtl-design/README.md` | Custom markdown | required (first-run) | Constraint-annotation note (SGDC section: `sync_cell` / `reset_synchronizer` / `set_case_analysis` / `quasi_static`). |
| `Design/specification/design.md` | markdown | required | spec main file; §1.4.1 Top-Level IO + §1.6 Clocks and Frequencies (authoritative period). |
| `Design/specification/manifest.json` | JSON | required | Enumerate `children`; lint-cdc reads each `<child>.md` body for SGDC annotation context (cross-domain signals / reset behavior / synchronizer hints). |
| `Design/specification/<child>.md` × N | markdown | required | Per-child body provides the SGDC annotation context. |
| `Design/specification/constraints/<TOP>.sgdc` | SGDC | required (cold-bootstrap) | SGDC seed source of truth; on first deployment bootstrap copies it to `{workdir}/scripts/constraints.sgdc`. The warm-bootstrap path (when `Design/lint-cdc/scripts/constraints.sgdc` already exists) does not read the spec seed; see `makefile-bootstrap.md`. |
| `Design/lint-cdc/scripts/constraints.sgdc` | SGDC | required (warm-bootstrap) | The SGDC with depth annotations persisted by the previous lint-cdc run. When present, bootstrap copies it to the working copy first, avoiding a full re-iteration of the depth annotations. |

When `{rework_trigger}` is injected, read additional context from the same directory as the trigger file: `stage_specific.violations[]` is the primary input; use its `id` / `rule` / `severity` fields to narrow the rework scope. The specific read scope is driven by the trigger's content; do not enumerate it ahead of time.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + `envelope.schema.json` | This stage's status contract (includes `violations[]`). |
| `lint-report.txt` | SpyGlass text report | Lint summary report. |
| `cdc-report.txt` | SpyGlass text report | CDC summary report (a missing file is treated as fail — `collect_report.py` exits 1 when the source report is not found). |
| `lint-violations.json` | JSON (`counts` + `violations[]`) | Structured lint findings from `collect_report.py`; Step 7 reads `counts.error` for the gate and `violations[]` for `result.json`. Listed in `artifacts[]` on the pass path → promoted to canonical, exactly like `lint-report.txt`. |
| `cdc-violations.json` | JSON (`counts` + `violations[]`) | As above, for CDC. |
| `scripts/constraints.sgdc` | SGDC | Working copy of the SGDC (the iteration site for depth annotations). When `status=pass`, list it in `result.json.artifacts[]`; it maps to the canonical `Design/lint-cdc/scripts/constraints.sgdc` and serves as the warm-start anchor for the next run. |

## Workflow

### Step 1: Read inputs and select routing branch

Based on whether `{rework_trigger}` is injected and whether the canonical path `Design/lint-cdc/result.json` already exists (a previous run has been promoted), choose one of three branches:

- **Trigger-driven rework** (`{rework_trigger}` injected): read the trigger's `stage_specific.violations[]` to produce this round's fix list. If the trigger file is unreadable, write `result.json` with `status=fail` and `stage_specific.fail_reason="rework_trigger not readable"`, then exit.
- **Incremental-update branch** (no trigger; canonical path already has prior artifacts): read the `Design/rtl-design/result.json` diff to determine the incremental scope.
- **First-run branch** (no trigger; canonical path has no prior artifacts): run the first-pass serial flow.

Then pre-check the external references: `Design/rtl-design/result.json.status=pass` AND `filelist.txt` and `README.md` are present AND the SGDC seed is available (warm: `Design/lint-cdc/scripts/constraints.sgdc` exists → preferred; cold: `Design/specification/constraints/<TOP>.sgdc` exists → fallback; neither → missing). If any required file is missing, write `status=fail` with `fail_reason="external reference missing: <path>"` and exit; if `Design/rtl-design/result.json.status≠pass`, write `fail_reason="external reference not pass: Design/rtl-design/result.json"` and exit.

When `{orchestrator_context_path}` is injected, Read that sibling file first as a fix-scope hint. It takes priority over both the trigger content (trigger-driven path) and the external-reference diff (incremental-update path) to further narrow the modification scope.

Steps 2–7 are mechanically identical across all three branches; the branch selected here sets only the **fix scope** — trigger-driven narrows the Step 4/5 triage to the trigger's `violations[]`, incremental-update to the `Design/rtl-design/result.json` diff, first-run covers everything — and `{orchestrator_context_path}` narrows it further when injected.

### Step 2: Bootstrap

Run `bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap_lint_cdc.sh --module {module} --workdir {workdir} [--top <TOP>]`. The script deploys the templates to `{workdir}`, substitutes the `MY_TOP` placeholder, and fills `scripts/constraints.sgdc` from the SGDC seed (warm → cold → template priority; see `references/makefile-bootstrap.md`). If `{workdir}/Makefile` already exists, treat the workdir as deployed and abort (a caller-placed `orchestrator-context.md` does NOT count as "deployed"). When `--top` is omitted, infer it from `Design/rtl-design/README.md` or `filelist.txt` (inference failure aborts with exit 1; stderr names the cause). The deployed `scripts/run_spyglass.sh`, `scripts/run.tcl`, `scripts/collect_report.py`, and `scripts/spyglass_lint.prj` are make-internal — `make lint` / `make cdc` is the interface, never the scripts directly; the only deployed files this stage edits are `scripts/constraints.sgdc` and `scripts/waiver.tcl`.

### Step 3: Add RTL custom-synchronizer annotations

Read the SGDC section of `Design/rtl-design/README.md`'s constraint-annotation note. Append `sync_cell -name <name>` for each custom synchronizer and `reset_synchronizer -name <name>` for each reset synchronizer to `scripts/constraints.sgdc`. If there are no custom synchronizers, skip this step.

### Step 4: `make lint`

runs SpyGlass lint and `collect_report.py`, which emits `lint-report.txt` (human) and `lint-violations.json` (structured: `counts` + `violations[]`, each with `severity` / `rule` / `file:line` / `message`). Read `lint-violations.json` and triage every `severity=error` entry:

- Test-control-signal false positives (`scan_en` / `test_mode` / `bypass`, etc.) → append `set_case_analysis <value> <port>` to `scripts/constraints.sgdc` and re-run `make lint` until they clear.
- Real lint violations → leave for the waiver pass in Step 6.

The script re-derives `counts` and `violations[]` on every run — you do not count by hand.

- **A non-zero `make` is authoritative — never infer success from `lint-violations.json` presence.** On a non-zero `make`, read `collect_report.py`'s stderr token and write `status=fail` with the matching `fail_reason`, then exit: `FAIL=missing` → `"lint report missing, not real sign-off"`; `FAIL=unparseable` → `"lint report unparseable"`; `FAIL=count_mismatch` → `"lint report parse incomplete (rows≠reported)"`. A non-zero `make` with **no** `FAIL=` token means SpyGlass itself did not complete (tool/license/crash, before `collect_report.py` ran) → `fail_reason="lint report missing, not real sign-off"`.

### Step 5: `make cdc`

runs SpyGlass CDC and `collect_report.py`, emitting `cdc-report.txt` + `cdc-violations.json`. Read `cdc-violations.json` and triage every `severity=error` entry:

- Quasi-static cross-domain false positives (see the SGDC section of `Design/rtl-design/README.md`'s constraint-annotation note) → append `quasi_static -name <signal>` to `scripts/constraints.sgdc` and re-run `make cdc` until they clear.
- Real CDC violations → leave for the waiver pass in Step 6.

The script re-derives the counts — you do not count by hand.

- **A non-zero `make` is authoritative — never infer success from `cdc-violations.json` presence.** On a non-zero `make`, read `collect_report.py`'s stderr token and write `status=fail` with the matching `fail_reason`, then exit: `FAIL=missing` → `"CDC report missing, not real sign-off"`; `FAIL=unparseable` → `"CDC report unparseable"`; `FAIL=count_mismatch` → `"CDC report parse incomplete (rows≠reported)"`. A non-zero `make` with **no** `FAIL=` token means SpyGlass itself did not complete (tool/license/crash, before `collect_report.py` ran) → `fail_reason="CDC report missing, not real sign-off"`.

### Step 6: Waivers

Write each reviewed waiver to `scripts/waiver.tcl`; each entry carries `-rules` and `-comment "<reason>. Owner: <owner> Date: <yyyy-mm-dd>"`. `waiver.tcl` is sourced automatically by `run.tcl` (when `SPYGLASS_STAGE=lint` or `all`). Re-run `make lint` to verify the waivers take effect.

### Step 7: Write `{workdir}/result.json`

(schema: `references/result.schema.json` + envelope). The gate reads the final `lint-violations.json` and `cdc-violations.json`: `status=pass` iff both `make` runs exited 0 **and** `counts.error == 0` in both; otherwise `status=fail`. Populate `violations[]` directly from the error-severity entries of the two `*-violations.json` (`id` / `rule` / `severity` from the parser; add a `reason`). Only `severity=error` items enter `violations[]`. **Artifacts** — every path listed in `artifacts[]` lands at the canonical `Design/lint-cdc/` path (pass and fail alike); a listed path that is not on disk fails to land there, so list only files that exist. On the **pass path**: `scripts/constraints.sgdc` (the warm-start anchor, promoted to canonical `Design/lint-cdc/scripts/constraints.sgdc`), both `*-report.txt`, and both `*-violations.json`. On any **early-fail path** (Steps 1/3/4/5): list only what was actually produced — typically just `scripts/constraints.sgdc` plus whichever report exists — **never** a `*-violations.json` the parser did not emit (write-fresh-or-nothing unlinks it on exit 3).

## Decision Rules

- Only `severity=error` items trigger `fail`; warning / info are treated as `pass`.
- It is preferable to run `make lint` first to converge `set_case_analysis` (removing test-control-signal false positives) before `make cdc`, or to run `make all` once (a single session sharing `elaborate`). The `make cdc` tool layer can run standalone (`cdc_setup` goals carry their own `elaborate`), but until the SGDC is stable CDC will report residual false positives.
- If the clock period and the SDC disagree, `Design/specification/design.md §1.6` clock frequency table is authoritative — consistency issues are a `specification` rework, not fixed in this stage.

## Red Flags

| Excuse | Reality |
|---|---|
| "`lint-report.txt` / `cdc-report.txt` isn't there but the run looked fine — mark pass" | A missing, **unparseable, or count-mismatched** report is a **fail**, not a pass. A non-zero `make` (see `collect_report.py`'s `FAIL=` token) → `status=fail` with `fail_reason`; absence/garbling of evidence is not evidence of clean. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Not reading the SGDC section of `Design/rtl-design/README.md`'s constraint-annotation note | After bootstrap, read it first to fill in `sync_cell` / `reset_synchronizer`. |
| Force-overwriting an already-deployed target directory | The bootstrap treats an existing `{workdir}/Makefile` as "already deployed" and aborts; back up first, then process. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written and passes schema validation.
- [ ] Every artifact path is listed in `result.json.artifacts[]`.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] The `result.json.status` decision has been written (`pass` or `fail`; the envelope does not accept `blocked`).
- [ ] Both `make` runs exited 0; `lint-report.txt` / `cdc-report.txt` and `lint-violations.json` / `cdc-violations.json` all exist.
- [ ] `sync_cell` / `reset_synchronizer` in `scripts/constraints.sgdc` cover every custom synchronizer in the RTL.
- [ ] `set_case_analysis` has cleared the test-control-signal false positives; `quasi_static` has cleared the quasi-static cross-domain false positives.
- [ ] Every `severity=error` item has been waived or written into `violations[]`.
- [ ] `scripts/constraints.sgdc` is listed in `result.json.artifacts[]` (on the `status=pass` path — promoted to `Design/lint-cdc/scripts/constraints.sgdc` as the warm-start anchor).

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`references/makefile-bootstrap.md`](references/makefile-bootstrap.md) — Bootstrap and Makefile-target quick reference.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
