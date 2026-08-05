---
name: lint-cdc
description: Use when running SpyGlass lint or CDC checks, analyzing violations, adding waivers, supplementing SGDC annotations, or re-running after RTL changes; not for synthesis or simulation.
---

# Lint / CDC

Your sole responsibility: converge SpyGlass lint and CDC to a clean error and warning count on
this module's RTL, and close the run through the `lintcdc` CLI.

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
changed since your last run: that narrows what you triage, never what the tool analyzes.

| Path | Use |
|---|---|
| `<annotations>/constraint-annotations.json` | The `sgdc` block per child: every depth annotation this RTL implies. `bootstrap` renders all four categories into the SGDC itself — you never transcribe them. Nothing upstream matched a name against the netlist, so a name SpyGlass cannot find surfaces here first, as its author's defect. Schema: `skills/rtl-design/references/constraint-annotations.schema.json`. |
| `<rtl>/rtl-files.json` | Per-child file layout, which `bootstrap` turns into `scripts/filelist.txt`. Schema: `skills/rtl-design/references/rtl-files.schema.json`. |
| `<sgdc_seed>/constraints/<TOP>.sgdc` | Clocks and resets from specification. `bootstrap` reads it every round, so a correction here arrives on its own; it is not yours to restate or override. |

Two files under `{workdir}` are yours, and both reach you holding the previous round's work
rather than a pristine template:

- `scripts/local.sgdc`: your own SGDC — the port/clock associations the seed cannot know.
- `scripts/waiver.tcl`: the waivers, each carrying its reason.

`scripts/constraints.sgdc` is the file SpyGlass reads and is **generated every round** from the
seed, the annotations and your `local.sgdc`, in that order. Editing it is pointless: the next
round overwrites it. That split is what lets an upstream correction reach the tool without
touching a round's own work, and it is why neither the clock/reset block nor the annotations are
yours to restate — a wrong one belongs to whoever declared it, and step 4 routes it there.

Everything else under `{workdir}` is produced by the tools you invoke, and `finalize`
enumerates it into `artifacts[]` for you.

## Workflow

### 1. Deploy

Run `bootstrap` to lay down the run scaffold:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/lintcdc/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

It deploys NO-CLOBBER so your two files survive, substitutes the `MY_TOP` placeholder, and
assembles `scripts/constraints.sgdc` from the specification seed, the generated annotations and
your `scripts/local.sgdc`. It aborts when `{workdir}/Makefile` already exists (the kernel-written
`dispatch.json` does not count as "deployed"), when the seed does not resolve, and when the
annotations sidecar is unreadable — the first two would leave SpyGlass analysing a design with no
clock declared, which it reports as a clean run. It reads the top-module name from
`manifest.module` when `--top` is omitted. Non-zero exit: stderr names the cause. `make` is the
interface to everything it deployed.

### 2. Constrain

The seed and the annotations are already in the assembled SGDC — you write neither. What is left
is what only this stage can know, into `scripts/local.sgdc`: the `abstract_port` associations
that bind a reset to the domain it resets and an input to its driving domain, without which CDC
cannot see the driver side of a crossing.

The seed's clock/reset block is not yours to override, and an annotation you disagree with is not
yours to correct. Both belong to whoever declared them, and step 4 routes a failure there — a
correction you make locally would leave that author's file wrong and synthesis reading it.

### 3. Converge

Run `make all` for a first pass, which shares one `elaborate` across both goals, or `make lint`
then `make cdc` when you want `set_case_analysis` settled before CDC runs. Each target ends in
`collect_report.py`, which writes `<kind>-report.txt` for a human and `<kind>-violations.json`
carrying `counts` plus one row per message.

Triage every `severity=error` and `severity=warning` row in both sidecars. The annotations
already suppressed the false-positive classes their authors declared, so a row that survived is
one of three things:

- **Acceptable anyway** → a `waive` in `scripts/waiver.tcl` carrying `-comment "<why>"`, then
  re-run that check to confirm it took. SpyGlass subtracts a waived message before anything
  counts it, so that text is the only surviving record of what you let through, and `finalize`
  BLOCKS on an entry without one.
- **A real defect, or an annotation its author never declared** → leave it. This run fails and
  step 4 attributes it.
- **An annotation that names something SpyGlass cannot find** (`checkSGDC_existence`, an
  `SGDC_*` Fatal) → also leave it. The name came verbatim from the sidecar, so the sidecar is
  wrong and rtl-design owns it. Do not repair it in `local.sgdc`: that hides the defect and
  leaves synthesis reading the same bad file.

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

It ANDs the two sidecars for the gate (`status=pass` iff both exist and `counts.error` and
`counts.warning` are both 0 in both), reads the SpyGlass version off the report, reshapes those
rows into `violations[]`, and enumerates `artifacts[]`. Both flags carry what the report cannot:

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
