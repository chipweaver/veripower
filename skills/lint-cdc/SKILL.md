---
name: lint-cdc
description: Use when running SpyGlass lint or CDC checks, analyzing violations, adding waivers, supplementing SGDC annotations, or re-running after RTL changes; not for synthesis or simulation.
---

# Lint / CDC

Your sole responsibility: run SpyGlass lint / CDC against the RTL and the SGDC, iterate on
depth annotations until the false positives clear, review the waivers, and close the run
through the `lintcdc` CLI's `finalize` verb.

## Iron Rule

- Write only under `{workdir}`. Every injected input location is read-only, as is every other
  stage's output.
- **Scripts are black boxes, never Read their source.** Invoke them per this skill's documented
  command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol
  (stderr, stdout verdict), not the source. Sole exception: debugging a suspected bug in a
  script itself.

## Input Artifacts

`{workdir}` is this run's workspace root; `{module}` is the module name.

Read `{workdir}/dispatch.json`: its `inputs` table maps each read-only upstream input to its
location, so `<key>` below denotes that location and you read `<key>/<subpath>`
(`rtl`/`annotations` both resolve to the rtl-design stage root).

| Path | Schema / Format | Use |
|---|---|---|
| `<rtl>/rtl-files.json` | `skills/rtl-design/references/rtl-files.schema.json` | Per-child RTL file layout; the bootstrap generates `scripts/filelist.txt` from it. |
| `<annotations>/constraint-annotations.json` | `skills/rtl-design/references/constraint-annotations.schema.json` | Per-child SGDC annotations (`sync_cell` / `reset_synchronizer` / `set_case_analysis` / `quasi_static`) in the child's real module names. |
| `<sgdc_seed>/constraints/<TOP>.sgdc` | SGDC | Cold-start seed for `scripts/constraints.sgdc`, used only on a genuinely first run. |

## Output Artifacts

Under `{workdir}`:

- `result.json`: this stage's status contract, written by `finalize` (`references/result.schema.json` + `envelope.schema.json`).
- `lint-report.txt` / `cdc-report.txt`: SpyGlass text reports, written by `make`.
- `lint-violations.json` / `cdc-violations.json`: the structured reports you triage, written by `make`.
- `scripts/constraints.sgdc`: the depth-annotation iteration site. **You edit it**, and it must appear in `result.json.artifacts[]`.
- `scripts/waiver.tcl`: the waivers you accept. **You edit it**, and it must appear in `result.json.artifacts[]`.

Those last two are carried into a fresh workdir from the previous round before you start, so
they may already hold converged annotations and reviewed waivers when you open them. Treat
what is there as work you inherited, not as a pristine template.

## Workflow

### Step 1: Determine scope

`{workdir}/dispatch.json`, when it carries a `scope` list, names the input files that changed
since this stage's last run: narrow the Step 4/5 triage to them. Without it the triage covers
everything. Steps 2–7 are mechanically identical either way, because the lint tool runs on the
whole RTL regardless.

### Step 2: Bootstrap

Run `bootstrap` to deploy the run scaffold into `{workdir}`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

It deploys the templates NO-CLOBBER, so an inherited `scripts/constraints.sgdc` /
`scripts/waiver.tcl` is never overwritten; substitutes the `MY_TOP` placeholder; and on a
genuinely first run fills `scripts/constraints.sgdc` from the SGDC seed. It aborts when
`{workdir}/Makefile` already exists (the kernel-written `dispatch.json` does not count as
"deployed"), and when `--top` is omitted it reads the name from `manifest.module`. Non-zero
exit: stderr names the cause.

The deployed `scripts/run_spyglass.sh`, `scripts/run.tcl`, `scripts/collect_report.py`, and
`scripts/spyglass_lint.prj` are make-internal. `make lint` / `make cdc` is the interface; the
only deployed files you edit are `scripts/constraints.sgdc` and `scripts/waiver.tcl`.

### Step 3: Add RTL custom-synchronizer annotations

Read `<annotations>/constraint-annotations.json` and union the `sgdc` block across every child.
Append `sync_cell -name <name>` for each name in `sync_cell` and `reset_synchronizer -name <name>`
for each name in `reset_synchronizer` to `scripts/constraints.sgdc`. Every child reporting `[]`
for both means there are no custom synchronizers: skip this step.

### Step 4: `make lint`

Run `make lint` to get a lint report. It runs SpyGlass and then `collect_report.py`, which emits
`lint-report.txt` (human) and `lint-violations.json` (structured: `counts` + `violations[]`, each
with `severity` / `rule` / `file:line` / `message`). It re-derives the counts on every run, so you
never count by hand.

Prefer running lint before CDC so `set_case_analysis` converges first, or `make all` once for a
single session that shares `elaborate`. `make cdc` does run standalone, but until the SGDC is
stable it reports residual test-control noise.

Read `lint-violations.json` and triage every `severity=error` entry:

- Test-control-signal false positives: a violation on a signal held to a constant in
  functional/mission mode (`scan_en` / `test_mode` / `bypass` tied inactive), so the structural
  flag exists only in the test configuration → append `set_case_analysis <value> <port>` to
  `scripts/constraints.sgdc` and re-run `make lint` until they clear. The children's
  `sgdc.set_case_analysis` entries already name their test-control ports and the functional
  value each takes; use those rather than guessing a value.
- Real lint violations → leave for the waiver pass in Step 6.

**A non-zero `make` is authoritative; never infer success from the `*-violations.json`
presence.** It ends the run. Go straight to Step 7 and pass the root cause you just read on
`collect_report.py`'s stderr as `--fail-reason`, because the parser deleted its sidecar and
the combiner can no longer see why. Nothing parses that string, so write the cause you
actually read rather than a category. The one thing stderr cannot tell you: a non-zero `make`
carrying **no** `FAIL=` token at all means SpyGlass itself never reached the report step (tool,
license, or crash), which is an environment failure and not a report defect. This protocol is
the same for `make cdc` in Step 5.

### Naming the fix owner

Whenever you close a run with `status=fail`, name the rule whose artifact must change and pass
it as `--fix-owner <rule>` in Step 7, which is what puts it in `stage_specific.fix_owner`. This
holds for a tool or license failure exactly as much as for a violation: a `fail_reason` that
names the guilty stage in prose while the flag was omitted reads to the caller as "this stage
could not tell", and brings a human in to re-derive an answer you already had.

You are the only party that read the report, so you are the only one who can answer this, and
the line a violation is reported at is not always the line that must change. The measured
evidence for the families where the report points at the wrong artifact is in
[`references/attribution-rules.md`](references/attribution-rules.md).

Omit the flag only when you cannot name an owner at all. It is the owner that decides, not
whether the rule family appears in that file: if you can say which stage's artifact is wrong,
name it even for a rule nobody has catalogued. An unnamed owner brings a human in, a wrong one
spends a rework round on a stage that cannot fix it.

### Step 5: `make cdc`

Run `make cdc` to get a CDC report, emitting `cdc-report.txt` + `cdc-violations.json` the same
way. Read `cdc-violations.json` and triage every `severity=error` entry:

- Quasi-static cross-domain false positives (the children's `sgdc.quasi_static` entries name
  them) → append `quasi_static -name <signal>` to `scripts/constraints.sgdc` and re-run
  `make cdc` until they clear.
- Real CDC violations → leave for the waiver pass in Step 6.

A non-zero `make cdc` follows the Step-4 protocol.

### Step 6: Waivers

Write each waiver to `scripts/waiver.tcl`; every entry carries `-rules` and a
`-comment "<why this violation is acceptable>"`. SpyGlass subtracts a waived message before the
parser counts anything, so the reason is the only record of what you let through: `finalize`
BLOCKS on an entry that has none. `run.tcl` sources the file for both goals, so a waiver or a
`set_option` written there applies to lint and CDC alike. Re-run the check whose violation you
waived to verify it took effect.

Waivers you inherited are NOT pre-validated: an entry written against an old finding can
silently swallow a NEW same-rule violation introduced by an RTL rework. On every run whose RTL
changed, re-review each inherited entry against this run's reports before Step 7: scope waivers
as narrowly as the rule allows (anchor to the design unit or instance, never a bare rule id when
avoidable) and delete entries whose original finding no longer exists.

### Step 7: Write `{workdir}/result.json` (mandatory)

Run `finalize` to write the envelope. Every run closes here, including the Step 4/5 early-fail,
and you never hand-assemble it, recount, or copy the header by hand:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py finalize \
  --workdir {workdir} --module <module> [--fix-owner <rule>] [--fail-reason "<cause>"]
```

It reads the two `*-violations.json` for the gate (`status=pass` iff both exist, meaning both
`make` runs reached `collect_report.py` cleanly, AND `counts.error == 0` in both), reads the
SpyGlass version off the report, reshapes the error-severity rows into `violations[]` (each
`reason` from the parser's tool `message`), and enumerates `artifacts[]`.

The two flags carry what the report cannot: `--fix-owner` because no rule id says whose artifact
must change, and `--fail-reason` because a `make` that died before the parser wrote its sidecar
left the cause only on stderr, where you read it. Supplying `--fail-reason` is itself the
declaration of failure, so pass it only when the run really failed. Everything else is
script-owned.

Exit 0 = `result.json` written, whether the status is pass or fail. Exit 2 is BLOCKED, never a
`status=fail`: an unreasoned waiver, an empty `--fail-reason`, or a program exception.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or
`STATUS: BLOCKED <one-line reason>` (when nothing could be written). What runs next is the
caller's decision, taken from `result.json`, not yours.
