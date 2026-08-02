---
name: synthesis
description: Use when running Design Compiler synthesis, analyzing timing/area/power reports, supplementing SDC exceptions, or re-synthesizing after RTL changes; not for power analysis or static timing.
---

# Synthesis

Your sole responsibility: carry this module's declared timing exceptions into the SDC, converge
Design Compiler against it, and close the run through the `synthesis` CLI.

## Iron Rule

- Write only under `{workdir}`. Every injected input location is read-only, as is every other
  stage's output.
- **Scripts are black boxes, never Read their source.** Invoke them per this skill's documented
  command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol
  (stderr, stdout verdict), not the source. Sole exception: debugging a suspected bug in a
  script itself.

## What you read, and what you edit

`{workdir}/dispatch.json` carries the `inputs` table below, so `<key>` denotes a location and you
read `<key>/<subpath>`. It also carries `scope` and `caused_by` when the kernel knows what changed
since your last run: those narrow which inherited exceptions you re-check and which violations you
triage, never which declarations you render — step 2 carries all of them every round, because the
SDC dc_shell reads is rebuilt every round.

| Path | Use |
|---|---|
| `<annotations>/constraint-annotations.json` | The `sdc` block per child: every timing exception and generated clock this RTL implies, in real module names. Its authors declared it and this stage is its only consumer. Schema: `skills/rtl-design/references/constraint-annotations.schema.json`. |
| `<rtl>/rtl-files.json` | Per-child file layout, which `bootstrap` turns into `scripts/rtl_load.tcl`. The RTL itself is under `<rtl>` too, and step 2 reads it for divider ratios. Schema: `skills/rtl-design/references/rtl-files.schema.json`. |
| `<sdc>/constraints/<TOP>.sdc` | Clocks and IO delays from specification. Round 1 cold-starts `constraints.sdc` from it; after that the carried copy wins, so a later correction here reaches you only if you carry it across in step 2. `bootstrap` says so when `scope` names this file. |
| `<ppa>/ppa.json` | The area and slack targets this run is judged against. `finalize` reads them itself; you read them when deciding which side of a PPA miss is wrong. Schema: `skills/specification/references/ppa.schema.json`. |

`LIB_DB` must be in the environment before `make`: `env.sh` refuses to run without it, and the
placeholder in `scripts/config.tcl` is a fallback for a `dc_shell` started outside the Makefile,
not a second way to set it. Exporting it after step 1 is fine.

One file under `{workdir}` is yours to edit, and it reaches you holding the previous round's work
rather than the specification SDC:

- `constraints.sdc`: every exception, every library value, and the `# notes:` that say why.

Treat what is in it as work you inherited. Re-check each exception against this run's reports and
delete one whose path no longer exists, but re-deriving a set you already have costs a full
re-synthesis per round. Everything else under `{workdir}` is produced by the tools you invoke, and
`finalize` enumerates it into `artifacts[]` for you.

## Workflow

### 1. Deploy

Run `bootstrap` to lay down the run scaffold:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/synthesis/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

It generates `scripts/rtl_load.tcl` and `scripts/config.tcl` from the rtl-design file layout, and
leaves an inherited `constraints.sdc` untouched — on a genuinely first run it cold-starts that
file from the specification SDC instead. It aborts when `{workdir}/Makefile` already exists (the
kernel-written `dispatch.json` does not count as "deployed"), and reads the top-module name from
`manifest.module` when `--top` is omitted. Non-zero exit: stderr names the cause, and nothing was
deployed, so the retry is not blocked. `make` is the interface to everything it deployed.

### 2. Constrain

Union the `sdc` block across every child of `<annotations>/constraint-annotations.json` and render
all three categories into `constraints.sdc` before you run anything:

| sidecar key | what it carries | what you write |
|---|---|---|
| `create_generated_clock` | `{module, pin}` — where a divider or PLL output leaves that child's RTL | `create_generated_clock` on that pin. `-source` is the master clock the specification SDC already declares; the divide factor comes from that module's RTL under `<rtl>` |
| `set_multicycle_path` | one free-form description per exception its author knows the design needs | `set_multicycle_path` naming the real startpoint / endpoint |
| `set_false_path` | the same, for architecturally unreachable paths | `set_false_path` naming the real startpoint / endpoint |

Every category is always present, so an empty array is that child's claim to have none. These are
design facts their authors declared rather than suppressions you are guessing at, which is why
all three go in one pass: each one you leave for dc_shell to surface costs a full synthesis
iteration to discover, and this sidecar is the only place rtl-design can state them.

Transcribe, never invent. lint-cdc reads this same sidecar for its SGDC side, so an exception you
add on your own authority has no counterpart there and the two constraint sets diverge silently.
A path nobody declared is step 3's to report, not yours to except.

Then settle what the seeded file itself asks for: the `set_clock_uncertainty -setup` / `-hold`
values its `;#` notes flag as placeholders, the `set_input_delay` / `set_output_delay` it already
carries per port, and `set_drive` / `set_load`, which it carries for no port — add those only
where the IO cell library documents them. Anything you leave at a placeholder, and anything you
decide not to add, needs a `# notes:` line saying why: this file is promoted, and the next reader
cannot tell a measured margin from a default or an omission from an oversight.

### 3. Converge

`make synthesis` runs `dc_shell` and outlives the foreground Bash timeout. Launch it as one
detached background job (`run_in_background=True`) from `{workdir}`, end your turn, and wait for
the harness completion notification; on wake read `run.log` once. The Makefile tees that log, and
the run never returns synchronously, so there is nothing to poll for.

Read the violated paths in `reports/timing_setup.rpt`, keeping each one's startpoint, endpoint and
slack. Step 2 already carried in every exception the design declares, so a path that is still
violating is one of two things:

- **A declaration you rendered wrong** — the description named a path and your SDC command does
  not match it. Fix the command and re-run.
- **A path nobody declared** — a real violation. Stop iterating and go to step 4. Its negative
  slack fails the `timing_slack_ns` target on its own, so the gate writes the `violations[]` row;
  what it cannot write is who must fix it.

Excepting the second kind here on your own judgement is the one way this stage can except its way
to a passing PPA verdict. If the path really is multicycle or false, its author is the one who
says so: name `rtl-design` in step 4 and it comes back declared, in the sidecar lint-cdc reads too.

A non-zero `make` ends the run with nothing to grade, so go straight to step 4 carrying the cause
you read in `run.log`.

### 4. Close

Run `finalize` to write the envelope. Every run ends here, a dc_shell that never reached the
reports included, and you never hand-assemble it:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/synthesis/__main__.py finalize \
  --workdir {workdir} [--fix-owner <rule>] \
  [--fail-reason "<cause>"]
```

It judges the PPA gate (worst setup slack = `min` of `Critical Path Slack` across every
clock-group block; area = `Total cell area`) against the targets it reads from `<ppa>/ppa.json`
itself — `area_um2` and `timing_slack_ns` only, an absent file or dim leaving that dimension
ungated — records both measurements as `stage_specific.ppa_actual[]`, reads the DC version off the
report header, and enumerates `artifacts[]`. A clean gate
is not enough for a pass: all three of `out/*_syn.{v,sdc,sdf}` must be on disk, and an incomplete
set is a `tooling` fail rather than a promoted synthesis the downstream stages cannot read.

The flags carry what the reports cannot:

- **`--fail-reason`**, which fills `stage_specific.fail_reason`, when dc_shell produced nothing
  gradeable: no license, an `analyze` / `elaborate` / `link` / `check_design` / `compile` abort, or
  a crash after the reports landed. You are the one who read `run.log`. Supplying it is itself the
  declaration of failure, so it wins over the gate and forces `status=fail` even where the reports
  parse clean; write the cause you actually read rather than a category, since nothing parses it.
- **`--fix-owner`** on every failure, tool and license failures included, since it is what fills
  `stage_specific.fix_owner`. A `fail_reason` naming the guilty stage in prose while the flag was
  omitted reads to the caller as "this stage could not tell", and brings a human in to re-derive
  an answer you already had. A PPA gate compares a measured value against a target and either side
  can be wrong, so before naming `rtl-design`, read `<ppa>/ppa.json`: a `dim` whose unit disagrees
  with the number stored in it — an `area_um2` target holding a NAND2 gate count, say — makes a
  conforming design look over-budget, and no rebuild converges against it. Name `specification`
  when the target is what is malformed, and omit the flag only when you have read both sides and
  still cannot name an owner.

Exit 0 means written, pass or fail. Exit 2 is BLOCKED and never a `status=fail`: an empty
`--fail-reason`, or a program exception. stderr names which.

## Return Contract

Emit `STATUS: DONE` as your last line once `result.json` exists, or
`STATUS: BLOCKED <one-line reason>` when nothing could be written. What runs next is the caller's
decision, taken from `result.json`.
