---
name: lint-cdc
description: Use when running SpyGlass lint or CDC checks, analyzing violations, adding waivers, supplementing SGDC annotations, or re-running after RTL changes; not for synthesis or simulation.
---

# Lint / CDC

Your sole responsibility: run SpyGlass lint / CDC against the RTL and the SGDC source of truth, iterate on depth annotations to suppress false positives, write the real violations into `result.json`, and persist the SGDC with the newly added depth annotations to lint-cdc's own canonical path (`Design/lint-cdc/scripts/constraints.sgdc`) for `carry_self` to carry forward into the next run.

## When to Use

- First-time bring-up of the SpyGlass lint / CDC environment.
- Run a lint or CDC check.
- Analyze violations and add waivers.
- Re-run lint / CDC after an RTL change.
- Supplement SGDC depth annotations (`sync_cell` / `reset_synchronizer` / `set_case_analysis` / `quasi_static`).

## Iron Rule

- The injected input locations (`<rtl>`, `<annotations>`, `<sgdc_seed>` — from `dispatch.json`) are read-only canonical: never modify anything under them (or any other stage's canonical output); the only files you write live under `{workdir}`. SGDC depth annotations belong to this stage's own carried file (`{workdir}/scripts/constraints.sgdc`, brought forward by `carry_self`); iterate only there, never write back to the spec source of truth.
- `{workdir}/scripts/constraints.sgdc` MUST be listed in `result.json.artifacts[]` — it then lands at the canonical path and `carry_self` carries it into the next run's workdir; without that entry the file is not promoted and depth annotations must re-converge from scratch.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |

### External reference inputs

Read `{workdir}/dispatch.json`: its `inputs` table maps each read-only upstream input to its location, so `<key>` below denotes that location and you read `<key>/<subpath>` (`rtl`/`annotations` both resolve to the rtl-design stage root).

| Path | Schema / Format | Use |
|---|---|---|
| `<rtl>/rtl-files.json` | `skills/rtl-design/references/rtl-files.schema.json` | Per-child RTL file layout; the bootstrap generates `scripts/filelist.txt` from it. |
| `<annotations>/constraint-annotations.json` | `skills/rtl-design/references/constraint-annotations.schema.json` | Per-child SGDC annotations (`sync_cell` / `reset_synchronizer` / `set_case_analysis` / `quasi_static`) in the child's real module names. |
| `<sgdc_seed>/constraints/<TOP>.sgdc` | SGDC | Cold-bootstrap seed — copied to `{workdir}/scripts/constraints.sgdc` on a genuinely first run; unused when a carried `scripts/constraints.sgdc` already exists (`makefile-bootstrap.md`). |

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + `envelope.schema.json` | This stage's status contract (includes `violations[]`). |
| `lint-report.txt` | SpyGlass text report | Lint summary report — a human deliverable; no downstream stage reads it. |
| `cdc-report.txt` | SpyGlass text report | CDC summary report — a human deliverable; no downstream stage reads it (missing = fail, `collect_report.py` exits 1). |
| `scripts/constraints.sgdc` | SGDC | Depth-annotation iteration site, edited by you; your own carried file — `carry_self` brings the canonical copy forward into each new run's workdir verbatim before you start, so it survives across runs. On `status=pass` list it in `artifacts[]` — promotion is what `carry_self` carries forward next time (Iron Rule). |
| `scripts/waiver.tcl` | TCL | Reviewed waivers, written by you (Step 6); your own carried file — same `carry_self` mechanism carries the canonical copy into each new run verbatim, which is what makes waivers survive across runs. Promoted on `status=pass`. |

## Workflow

### Step 1: Read inputs and determine scope

Pre-check the external references: `<rtl>/rtl-files.json` and `<annotations>/constraint-annotations.json` are present AND the SGDC seed is available (carried: `{workdir}/scripts/constraints.sgdc` already present, brought forward by `carry_self` before this run started → preferred; cold: `<sgdc_seed>/constraints/<TOP>.sgdc` exists → fallback; neither → missing). If any required file is missing, write `status=fail` with `fail_reason="external reference missing: <path>"` and exit.

Determine this round's fix scope from the first available source:
`{workdir}/dispatch.json`, when it carries a `scope` list, names the input files that changed since this stage's last run: narrow the Step 4/5 triage to them. Without it the triage covers everything, whether this is a first delivery or a re-verify of an already-promoted run; the lint tool runs on the whole RTL either way, so there is simply no change-set to narrow the triage to.

Steps 2–7 are mechanically identical regardless of scope; the scope set here narrows only the Step 4/5 triage (a scoped run narrows to the `scope` set; an unscoped one covers everything).

### Step 2: Bootstrap

Run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

The script deploys the templates to `{workdir}` NO-CLOBBER — a `scripts/constraints.sgdc` / `scripts/waiver.tcl` already carried into the workdir by `carry_self` before this run started is never overwritten — substitutes the `MY_TOP` placeholder, and on a genuinely first run (no carried `scripts/constraints.sgdc`) fills it from the SGDC seed (cold → template priority; see `references/makefile-bootstrap.md`). If `{workdir}/Makefile` already exists, treat the workdir as deployed and abort (the kernel-written `dispatch.json` does NOT count as "deployed"). When `--top` is omitted, it is read from `manifest.module` (a missing name aborts with exit 1; stderr names the cause). The deployed `scripts/run_spyglass.sh`, `scripts/run.tcl`, `scripts/collect_report.py`, and `scripts/spyglass_lint.prj` are make-internal — `make lint` / `make cdc` is the interface, never the scripts directly; the only deployed files you edit are `scripts/constraints.sgdc` and `scripts/waiver.tcl`.

### Step 3: Add RTL custom-synchronizer annotations

Read `<annotations>/constraint-annotations.json` and union the `sgdc` block across every child. Append `sync_cell -name <name>` for each name in `sync_cell` and `reset_synchronizer -name <name>` for each name in `reset_synchronizer` to `scripts/constraints.sgdc`. Every child reporting `[]` for both means there are no custom synchronizers — skip this step.

### Step 4: `make lint`

runs SpyGlass lint and `collect_report.py`, which emits `lint-report.txt` (human) and `lint-violations.json` (structured: `counts` + `violations[]`, each with `severity` / `rule` / `file:line` / `message`). Read `lint-violations.json` and triage every `severity=error` entry:

- Test-control-signal false positives — a violation on a signal held to a constant in functional/mission mode (`scan_en` / `test_mode` / `bypass` tied inactive), so the structural flag exists only in the test configuration → append `set_case_analysis <value> <port>` to `scripts/constraints.sgdc` (pin the functional value) and re-run `make lint` until they clear. The children's `sgdc.set_case_analysis` entries already name their test-control ports and the functional value each takes — use those rather than guessing a value.
- Real lint violations → leave for the waiver pass in Step 6.

The script re-derives `counts` and `violations[]` on every run — you do not count by hand.

- **A non-zero `make` is authoritative — never infer success from the `*-violations.json` presence.** This `FAIL=` protocol covers both `make lint` (this step) and `make cdc` (Step 5); the report label is `lint` for `make lint`, `CDC` for `make cdc`. On a non-zero `make`, read `collect_report.py`'s stderr token and write `status=fail` with the matching `fail_reason`, then exit: `FAIL=missing` → `"<label> report missing, not real sign-off"`; `FAIL=unparseable` → `"<label> report unparseable"`; `FAIL=count_mismatch` → `"<label> report parse incomplete (rows≠reported)"`. A non-zero `make` with **no** `FAIL=` token means SpyGlass itself did not complete (tool/license/crash, before `collect_report.py` ran) → `fail_reason="<label> report missing, not real sign-off"`.

### Naming the fix owner

Whenever you close a run with `status=fail`, decide who must act and pass it as
`--fix-owner <rule>` to the combiner (Step 6). You are the only party that read the report, so
you are the only one who can answer this, and the line a violation is reported at is not always
the line that must change. Which rule family means whose artifact, with the measured evidence
behind each: `${CLAUDE_SKILL_DIR}/references/attribution-rules.md`. When it does
not resolve, omit the flag — an unnamed owner brings a human in, a wrong one spends a rework
round on a stage that cannot fix it.

### Step 5: `make cdc`

runs SpyGlass CDC and `collect_report.py`, emitting `cdc-report.txt` + `cdc-violations.json`. Read `cdc-violations.json` and triage every `severity=error` entry:

- Quasi-static cross-domain false positives (the children's `sgdc.quasi_static` entries name them) → append `quasi_static -name <signal>` to `scripts/constraints.sgdc` and re-run `make cdc` until they clear.
- Real CDC violations → leave for the waiver pass in Step 6.

The script re-derives the counts — you do not count by hand.

- **A non-zero `make cdc`** follows the same `FAIL=` protocol as Step 4 (report label `CDC`): read `collect_report.py`'s stderr token and write `status=fail` + the matching `fail_reason`, then exit.

### Step 6: Waivers

Write each reviewed waiver to `scripts/waiver.tcl`; each entry carries `-rules` and `-comment "<reason>. Owner: <owner> Date: <yyyy-mm-dd>"`. `waiver.tcl` is sourced automatically by `run.tcl` (when `SPYGLASS_STAGE=lint` or `all`). Re-run `make lint` to verify the waivers take effect.

Carried-forward waivers are NOT pre-validated: `carry_self` carries the canonical `waiver.tcl` verbatim, so an entry written against an old finding can silently swallow a NEW same-rule violation introduced by an RTL rework. On every run whose RTL changed, re-review each carried entry against this run's reports before Step 7: scope waivers as narrowly as the rule allows (anchor to the design unit/instance, never a bare rule id when avoidable) and delete entries whose original finding no longer exists.

### Step 7: Write `{workdir}/result.json` (mandatory)

Run the result combiner; do not hand-assemble the envelope, recount, or copy the header by hand.
Every field but one is script-derived; `--fix-owner` is yours (below):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py finalize \
  --workdir {workdir} --module <module> [--top <TOP>]
```

The combiner reads the two `*-violations.json` for the gate (`status=pass` iff both exist — both
`make` reached `collect_report.py` cleanly — AND `counts.error == 0` in both), copies
`lint_counts` / `cdc_counts` from them, derives the slim header (`top_module` / `tool` from the
report), reshapes the error-severity rows into `violations[]` (deriving each `reason` from the
parser's tool `message`), enumerates `artifacts[]`, and writes the complete `result.json`. Exit 0 =
result.json written (status pass or fail). A non-zero combiner exit is a program exception (BLOCKED),
not a `status=fail`.

The Step 4/5 `FAIL=` early-fail handling is unchanged: on a non-zero `make` you still act on
`collect_report.py`'s `FAIL=` token and write `status=fail` + the matching `fail_reason` directly
(the parser unlinked the `*-violations.json`, so the combiner's gate would also fail on the missing
file — but your `FAIL=` mapping carries the precise tool-level reason, so write that envelope
in Steps 4/5 rather than deferring to the combiner). The combiner owns the **clean-path** assembly and
the **error-severity gate** (both reports present, `counts.error > 0`).

Every field in result.json but `fix_owner` is script-derived: the per-error `reason` comes from the
parser's tool `message`, and `failure_kind` from the SpyGlass rule family. You supply `--fix-owner`,
and nothing else.

## Decision Rules

- Only `severity=error` items trigger `fail`; warning / info are treated as `pass`.
- It is preferable to run `make lint` first to converge `set_case_analysis` (removing test-control-signal false positives) before `make cdc`, or to run `make all` once (a single session sharing `elaborate`). The `make cdc` tool layer can run standalone (`cdc_setup` goals carry their own `elaborate`), but until the SGDC is stable CDC will report residual false positives.
- Clock and IO facts arrive via the SGDC seed (`<sgdc_seed>/constraints/*.sgdc`, produced by `derive-constraints`). SDC≡SGDC holds **by construction**: both are rendered from the same `clocks.json` entry via one shared clock partition (F1), and that equality is asserted in `tests/unit/test_spec_constraints.py` rather than re-derived from the emitted text at runtime. This stage does not re-check spec-vs-SDC consistency.

## Red Flags

| Excuse | Reality |
|---|---|
| "`lint-report.txt` / `cdc-report.txt` isn't there but the run looked fine — mark pass" | A missing, **unparseable, or count-mismatched** report is a **fail**, not a pass. A non-zero `make` (see `collect_report.py`'s `FAIL=` token) → `status=fail` with `fail_reason`; absence/garbling of evidence is not evidence of clean. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Not reading `<annotations>/constraint-annotations.json` | After bootstrap, read it first to fill in `sync_cell` / `reset_synchronizer`; the annotations are per-child, so union them across the whole roster. |
| Force-overwriting an already-deployed target directory | The bootstrap treats an existing `{workdir}/Makefile` as "already deployed" and aborts; back up first, then process. |

## Completion Gate

- [ ] result.json was written by the `lintcdc` CLI's `finalize` verb (it owns status / lint_counts / cdc_counts / violations / the reproducibility header / artifacts[]; the per-error reason is derived from the tool message — no agent input).
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] The `result.json.status` decision has been written (`pass` or `fail`; the envelope does not accept `blocked`).
- [ ] `sync_cell` / `reset_synchronizer` in `scripts/constraints.sgdc` cover every custom synchronizer in the RTL.
- [ ] `set_case_analysis` has cleared the test-control-signal false positives; `quasi_static` has cleared the quasi-static cross-domain false positives.
- [ ] Every `severity=error` item has been waived or written into `violations[]`.
- [ ] `scripts/constraints.sgdc` is listed in `result.json.artifacts[]` (on the `status=pass` path; the Iron Rule covers promotion + carry-forward).

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write). The harness uses this signal to fire the Task-completion notification; the caller then decides based on `result.json`.

## Bundled References

- [`references/makefile-bootstrap.md`](references/makefile-bootstrap.md) — Bootstrap and Makefile-target quick reference.
- `${CLAUDE_SKILL_DIR}/references/attribution-rules.md` — which SpyGlass rule family means whose artifact must change; the `--fix-owner` decision.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
