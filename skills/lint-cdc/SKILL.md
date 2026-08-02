---
name: lint-cdc
description: Use when running SpyGlass lint or CDC checks, analyzing violations, adding waivers, supplementing SGDC annotations, or re-running after RTL changes; not for synthesis or simulation.
---

# Lint / CDC

Your sole responsibility: converge SpyGlass lint and CDC to a clean error count on this
module's RTL, and close the run through the `lintcdc` CLI.

## Iron Rule

- Write only under `{workdir}`. Every injected input location is read-only, as is every other
  stage's output.
- **Scripts are black boxes, never Read their source.** Invoke them per this skill's documented
  command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol
  (stderr, stdout verdict), not the source. Sole exception: debugging a suspected bug in a
  script itself.

## What you read, and what you edit

`{workdir}/dispatch.json` carries the `inputs` table below, so `<key>` denotes a location and
you read `<key>/<subpath>`. It also carries a `scope` list when the kernel knows which inputs
changed since your last run: that narrows what you triage, never what the tool analyzes — except
when it names the SGDC seed, which is the one input whose change you must carry into a file that
would otherwise never see it.

| Path | Use |
|---|---|
| `<annotations>/constraint-annotations.json` | The `sgdc` block per child: every depth annotation this RTL implies, in real module names. The child that wrote the RTL declared them; nothing upstream matched a name against it, so an annotation naming a module SpyGlass cannot find surfaces here first. Schema: `skills/rtl-design/references/constraint-annotations.schema.json`. |
| `<rtl>/rtl-files.json` | Per-child file layout, which `bootstrap` turns into `scripts/filelist.txt`. Schema: `skills/rtl-design/references/rtl-files.schema.json`. |
| `<sgdc_seed>/constraints/<TOP>.sgdc` | Clocks, resets and port associations from specification. Round 1 cold-starts `scripts/constraints.sgdc` from it; after that the carried copy wins, so a later correction here reaches you only if you carry it across. `bootstrap` says so when `scope` names this file. |

Two files under `{workdir}` are yours to edit, and both reach you holding the previous round's
work rather than a pristine template:

- `scripts/constraints.sgdc`: the seed plus every depth annotation.
- `scripts/waiver.tcl`: the waivers, each carrying its reason.

Everything else under `{workdir}` is produced by the tools you invoke, and `finalize`
enumerates it into `artifacts[]` for you.

## Workflow

### 1. Deploy

Run `bootstrap` to lay down the run scaffold:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

It deploys NO-CLOBBER so your two files survive, substitutes the `MY_TOP` placeholder, and
cold-starts `scripts/constraints.sgdc` from the seed on a genuinely first run. It aborts when
`{workdir}/Makefile` already exists (the kernel-written `dispatch.json` does not count as
"deployed"), and reads the top-module name from `manifest.module` when `--top` is omitted.
Non-zero exit: stderr names the cause. `make` is the interface to everything it deployed.

### 2. Transcribe the annotations

Union the `sgdc` block across every child of `<annotations>/constraint-annotations.json` and
append all four categories to `scripts/constraints.sgdc` before you run anything:

| sidecar key | SGDC line |
|---|---|
| `sync_cell` | `sync_cell -name <module>` |
| `reset_synchronizer` | `reset_synchronizer -name <net>` |
| `set_case_analysis` | `set_case_analysis -name <port> -value <value>` |
| `quasi_static` | `quasi_static -name <signal>` |

Every category is always present, so an empty array is that child's claim to have none. These
are design facts their authors declared rather than suppressions you are guessing at, which is
why all four go in one pass: each one you left for the tool to surface would cost a full
SpyGlass iteration to discover.

Use those exact forms, and note that the two synchronizer commands do not take the same kind of
name: `sync_cell` names the module, `reset_synchronizer` names the synchronized reset net it
drives. Giving `reset_synchronizer` a module name is `checkSGDC_existence` + a Fatal that aborts
rule checking for the whole run, and the sidecar it leaves behind reads CLEANER than the truth —
measured on `vL-2016.06`, the aborted run reported 0 unsynchronized crossings where the same RTL
really had 6. SGDC also takes `set_case_analysis` by flag, and the positional spelling that is
correct in SDC (`set_case_analysis 0 scan_en`) is a syntax fatal in the same way.

Transcribe, never invent. synthesis reads this same sidecar for its SDC side, so an annotation
you add here on your own authority has no SDC counterpart and the two constraint sets diverge
silently. A false positive the sidecar never declared is a gap in its author's work, and step 4
routes it there.

### 3. Converge

Run `make all` for a first pass, which shares one `elaborate` across both goals, or `make lint`
then `make cdc` when you want `set_case_analysis` settled before CDC runs. Each target ends in
`collect_report.py`, which writes `<kind>-report.txt` for a human and `<kind>-violations.json`
carrying `counts` plus one row per message.

Triage every `severity=error` row in both sidecars. Step 2 already suppressed the false-positive
classes, so a row that survived is one of two things:

- **Acceptable anyway** → a `waive` in `scripts/waiver.tcl` carrying `-comment "<why>"`, then
  re-run that check to confirm it took. SpyGlass subtracts a waived message before anything
  counts it, so that text is the only surviving record of what you let through, and `finalize`
  BLOCKS on an entry without one.
- **A real defect, or an annotation its author never declared** → leave it. This run fails and
  step 4 attributes it.

Re-review inherited waivers on any run whose RTL changed: an entry written against an old
finding silently swallows a new same-rule violation. Scope each as narrowly as the rule allows,
anchoring to the design unit or instance rather than a bare rule id, and delete entries whose
original finding is gone.

A non-zero `make` ends the run with nothing to triage, so go straight to step 4 carrying the
cause from `collect_report.py`'s stderr. Never read success from a `*-violations.json` being
present: when SpyGlass itself fatals, `make` stops before the parser runs, so the sidecar from
an earlier iteration is still sitting there with its old counts.

### 4. Close

Run `finalize` to write the envelope. Every run ends here, a failed `make` included, and you
never hand-assemble it:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py finalize \
  --workdir {workdir} [--fix-owner <rule>] [--fail-reason "<cause>"]
```

It ANDs the two sidecars for the gate (`status=pass` iff both exist and `counts.error == 0` in
both), reads the SpyGlass version off the report, reshapes the error rows into `violations[]`,
and enumerates `artifacts[]`. Both flags carry what the report cannot:

- **`--fail-reason`**, which fills `stage_specific.fail_reason`, when a `make` died before the
  parser wrote its sidecar, so the cause exists only on the stderr you read. Supplying it is
  itself the declaration of failure. A `make` that failed carrying no `FAIL=` token at all never
  reached the report step, which is an environment failure rather than a report defect.
- **`--fix-owner`** on every failure, tool and license failures included, since it is what fills
  `stage_specific.fix_owner`. You are the only party that read the report, and the line a
  violation is reported at is not always the line that must change:
  [`references/attribution-rules.md`](references/attribution-rules.md) records the measured
  families where it points elsewhere. Name the stage whose artifact is wrong even for a rule
  nobody has catalogued; omit the flag only when you cannot name one at all.

Exit 0 means written, pass or fail. Exit 2 is BLOCKED and never a `status=fail`: an unreasoned
waiver, an empty `--fail-reason`, or a program exception.

## Return Contract

Emit `STATUS: DONE` as your last line once `result.json` exists, or
`STATUS: BLOCKED <one-line reason>` when nothing could be written. What runs next is the
caller's decision, taken from `result.json`.
