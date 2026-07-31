---
name: synthesis
description: Use when running Design Compiler synthesis, analyzing timing/area/power reports, supplementing SDC exceptions, or re-synthesizing after RTL changes; not for power analysis or static timing.
---

# Synthesis

Your sole responsibility: carry this module's declared timing exceptions into the SDC, converge
Design Compiler against it, and close the run through the `synthesis` CLI's `finalize` verb, which
judges the area_um2 / timing_slack_ns PPA dimensions.

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
| `<rtl>/rtl-files.json` | `skills/rtl-design/references/rtl-files.schema.json` | Per-child RTL file layout; the bootstrap generates `scripts/rtl_load.tcl` from it. |
| `<annotations>/constraint-annotations.json` | `skills/rtl-design/references/constraint-annotations.schema.json` | The `sdc` block per child: every timing exception and generated clock this RTL implies, in real module names. Its authors declared it, and this stage is its only consumer. |
| `<sdc>/constraints/<TOP>.sdc` | SDC | Cold-start seed for `constraints.sdc`, used only on a genuinely first run. |
| `<ppa>/ppa.json` | `skills/specification/references/ppa.schema.json` | The targets this run is judged against; `finalize` reads them itself, and you read them when deciding which side of a PPA miss is wrong. |

## Output Artifacts

Under `{workdir}`:

- `result.json`: this stage's status contract, written by `finalize` (`references/result.schema.json` + `envelope.schema.json`; `stage_specific.ppa_actual[]` on a pass, `violations[]` on a PPA fail).
- `out/*_syn.v` / `out/*_syn.sdc` / `out/*_syn.sdf`: the gate-level netlist, post-synthesis constraints and SDF, written by `make`.
- `reports/qor.rpt` / `area.rpt` / `timing_setup.rpt` / `timing_hold.rpt` / `power.rpt` / `check_design.rpt`: the DC report set, written by `make`. `timing_setup.rpt` is what you triage in Step 6.
- `constraints.sdc`: the timing-exception iteration site. **You edit it** (Steps 4/6). It is the only deployed file you edit.
- `scripts/config.tcl`: `TOP` + a `LIB_DB` fallback for a `dc_shell` started outside the Makefile, written by the bootstrap.

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
round answers, whose `stage_specific.violations[]` say what missed. That narrows which inherited
exceptions you re-check and which violations you triage, never which declarations you render:
Step 4 carries all of them every round, because the SDC dc_shell reads is rebuilt every round.
With neither key, nothing is narrowed.

### Step 2: Bootstrap

Run `bootstrap` to deploy the run scaffold into `{workdir}`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/synthesis/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

It deploys the templates, generates `scripts/rtl_load.tcl` (the `analyze` list, plus each child's
`incdirs[]` on `search_path`) and `scripts/config.tcl` from the rtl-design file layout, and leaves
an inherited `constraints.sdc` untouched — on a genuinely first run it seeds that file from
`<sdc>/constraints/<TOP>.sdc` instead. It aborts when `{workdir}/Makefile` already exists (the
kernel-written `dispatch.json` does not count as "deployed"), and when `--top` is omitted it reads
the name from `manifest.module`. Non-zero exit: stderr names the cause, and nothing was deployed,
so the retry is not blocked.

The deployed `Makefile`, `env.sh`, `scripts/dc_run.tcl`, `scripts/rtl_load.tcl` and
`scripts/config.tcl` are make-internal. `make synthesis` is the interface; the only deployed file
you edit is `constraints.sdc`.

### Step 3: Export `LIB_DB`

`export LIB_DB=<path>` to the standard-cell Liberty `.db`. It has to be in the environment:
`env.sh` refuses to run without it, so `make synthesis` never reaches `dc_shell`, and the
placeholder in `scripts/config.tcl` is a fallback for a `dc_shell` started outside the Makefile,
not a second way to set it. Exporting after Step 2 is fine.

### Step 4: Edit `{workdir}/constraints.sdc`

Union the `sdc` block across every child of `<annotations>/constraint-annotations.json` and render
all three categories into `constraints.sdc` before you run anything:

| sidecar key | what it carries | what you write |
|---|---|---|
| `create_generated_clock` | `{module, pin}` — where a divider or PLL output leaves that child's RTL | `create_generated_clock` on that pin. `-source` is the master clock the specification SDC already declares; the divide factor comes from the divider RTL at that module, which you can read under `<rtl>` |
| `set_multicycle_path` | one free-form description per exception its author knows the design needs | `set_multicycle_path` naming the real startpoint / endpoint |
| `set_false_path` | the same, for architecturally unreachable paths | `set_false_path` naming the real startpoint / endpoint |

All three keys are required of every child, so an empty array is that child's claim to have none.
These are design facts the RTL authors declared, not suppressions you are guessing at, which is
why they all go in before the first run: each one you leave for dc_shell to surface costs a full
synthesis iteration to rediscover, and the same sidecar is the only place rtl-design can state
them — it has no other backstop.

Transcribe, never invent. lint-cdc reads this same sidecar for its SGDC side, so an exception you
add on your own authority has no counterpart there and the two constraint sets diverge silently.
A path nobody declared is handled in Step 6, not here.

Then set what the file itself asks for:

- Replace the `set_clock_uncertainty -setup` / `-hold` placeholder values with the values from the process library (each carries its own `;#` note in the generated file; when undocumented, keep setup=`0.2 ns` / hold=`0.0 ns` and add a note — pre-CTS hold = 0, and a single value for both would read every pre-CTS path as hold-VIOLATED).
- Confirm the `set_input_delay` / `set_output_delay` the file already carries per port (replace from the interface spec when available).
- Add `set_drive` / `set_load` per the IO cell library. The specification SDC carries neither, so there is nothing to replace: add them when the library documents drive strengths and loads, and otherwise leave them out.

Every placeholder value you keep, and every constraint you decided not to add, needs a `# notes:`
comment saying why, because this file is promoted and the next reader cannot tell a measured
margin from a default or an omission from an oversight. Do not guess port names from an interface
spec you do not have.

### Step 5: First synthesis run

`make synthesis` runs `dc_shell` and can outrun the foreground Bash timeout. Launch it as one
detached background job (`run_in_background=True`) from `{workdir}` (the Makefile tees `run.log`),
then end your turn and wait for the harness completion notification. On wake, read `run.log` once
(tail + exit status) and proceed. The result never returns synchronously, so foregrounding it or
polling with `sleep` / `pgrep` / `until … done` buys nothing and burns the turn budget that the
notification gives you for free.

### Step 6: Triage what the report shows

Read the violated paths in `reports/timing_setup.rpt`, keeping each one's startpoint, endpoint and
slack. Step 4 already carried in every exception the design declares, so a path that is still
violating is one of two things, and neither is yours to except:

- **A declared exception you rendered wrong** — the description named a path, and the SDC command
  you wrote does not match it. Fix the command and re-run (same detached-background protocol as
  Step 5).
- **A path nobody declared** — a real violation. Stop iterating and close the run at Step 7. The
  negative slack fails the `timing_slack_ns` target on its own, so the gate writes the
  `violations[]` row; what it cannot write is who must fix it.

Adding an exception here on your own judgement is the one way this stage can except its way to a
passing PPA verdict, which is why Step 4 is the only place exceptions enter. If the path really is
multicycle or false, its author is the one who says so: name `rtl-design` in Step 7 and it comes
back declared, in the sidecar lint-cdc reads too.

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
clock-group blocks; area = `Total cell area`), reads the DC version off the report header,
enumerates `artifacts[]`, and writes the complete `result.json`. A clean gate is not enough for a
pass: it also requires all three of `out/*_syn.{v,sdc,sdf}` on disk, and reports an incomplete set
as a `tooling` fail rather than promoting a synthesis the downstream stages cannot read.

The two failure flags carry what the reports cannot. Pass them when dc_shell produced nothing
gradeable — no license, an `analyze` / `elaborate` / `link` / `check_design` / `compile` abort, a
crash after the reports landed — because you are the one who read `run.log`. `--fail-reason` is
itself the declaration of failure, so it wins over the gate and forces `status=fail` even where
the reports parse clean; pass it only when the run really failed, and write the cause you actually
read rather than a category (nothing parses the string). `--failure-kind` lands in
`stage_specific.failure_kind` and splits the one thing an absent report cannot tell you apart:
`infra` when DC never ran, `tooling` when it ran and its output is unusable. The third value,
`ppa`, is the gate's to write and never yours.

Exit 0 = `result.json` written, whether the status is pass or fail. Exit 2 is BLOCKED, never a
`status=fail`: an empty `--fail-reason`, one without a `--failure-kind`, or a program exception.
stderr names which.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or
`STATUS: BLOCKED <one-line reason>` (when nothing could be written). What runs next is the
caller's decision, taken from `result.json`, not yours.
