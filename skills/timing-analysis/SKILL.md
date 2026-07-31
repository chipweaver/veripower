---
name: timing-analysis
description: Use when running static timing analysis on synthesis netlist, analyzing setup/hold violations, reviewing timing reports, or re-analyzing after synthesis changes; not for synthesis or power analysis.
---

# Static Timing Analysis

Your sole responsibility: run PrimeTime over the post-synthesis netlist, independently of the
timing engine inside synthesis, and close the run through the `timing` CLI. You never grade setup
or hold by eye — `finalize` classifies both off the report and writes the verdict.

## Iron Rule

- Write only under `{workdir}`. Every injected input location is read-only, as is every other
  stage's output.
- **Scripts are black boxes, never Read their source.** Invoke them per this skill's documented
  command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol
  (stderr, stdout verdict), not the source. Sole exception: debugging a suspected bug in a
  script itself.

## What you read, and what you produce

`{workdir}/dispatch.json` carries the `inputs` table, but you open none of what it points at:
`bootstrap` resolves `<TOP>` from the single `out/<TOP>_syn.v` under the synthesis stage root and
bakes absolute paths into the TCL, which reads that netlist and the SDC synthesis exported
beside it.

The one thing you supply is `LIB_DB`, the std-cell Liberty `.db` synthesis linked against.

Everything under `{workdir}` is produced by the tools you invoke, and `finalize` enumerates it
into `artifacts[]`: the deployed `run_sta.tcl` and `config.tcl`, plus `timing-report.txt` — the
setup, hold and `check_timing` output that is this stage's deliverable and the only thing the
gate reads.

## Workflow

### 1. Deploy

Export `LIB_DB`, then run `bootstrap` to lay down the run scaffold:

```bash
export LIB_DB=<path-to-slow.db>
python3 ${CLAUDE_SKILL_DIR}/scripts/timing/__main__.py bootstrap --workdir {workdir}
```

It deploys `run_sta.tcl` + `config.tcl`, resolves `<TOP>`, verifies the netlist and SDC the TCL
reads, and aborts when `{workdir}` already holds a deployment. `pt_shell` reads `LIB_DB` out of
the `config.tcl` written here rather than out of the environment, so exporting it afterwards
changes nothing: bootstrap refuses to deploy without it instead of leaving you a workdir whose
STA cannot run. Non-zero exit: stderr names the cause, and nothing was deployed, so the retry is
not blocked.

### 2. Run the STA

Run PrimeTime from the workdir, so its auto-logs (`pt_shell_command.log`, `.svf`) land inside the
gitignored workdir rather than the tree root:

```bash
cd {workdir} && pt_shell -f run_sta.tcl
```

The TCL reports setup and hold, runs `check_timing`, and redirects all three into
`{workdir}/timing-report.txt`. Read what it printed rather than what it returned: `pt_shell`
exits 0 even on a script error, so its exit code settles nothing.

### 3. Close

Run `finalize` to write the envelope. Every run ends here, a `pt_shell` that never reached the
report included, and you never hand-assemble it:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/timing/__main__.py finalize \
  --workdir {workdir} --module <module> [--fix-owner <rule>] \
  [--fail-reason "<cause>" --failure-kind {infra|tooling}]
```

It classifies each direction on the report's `(MET)` / `(VIOLATED)` marker — never the displayed
number, which prints `0.00` for a violation smaller than the reported precision — records the
worst slack and worst path per direction into `stage_specific.timing`, lists the binding violator
per failing direction into `stage_specific.violations[]`, reads the PrimeTime version off the
report header, and enumerates `artifacts[]`.

Two MET markers are not enough for a pass. `check_timing` counts the endpoints the SDC left
unconstrained and the register clock pins with no clock, and a run carrying either graded a
fraction of the design: the markers describe the paths PrimeTime analyzed and say nothing about
the ones it was never asked to. That is a `tooling` fail rather than a `ppa` one, and the SDC it
read is synthesis's export of what specification declared, so read both before naming the owner.

The flags carry what the report cannot:

- **`--fail-reason`**, which fills `stage_specific.fail_reason`, when `pt_shell` produced nothing
  gradeable: no license, a `link_design` or `read_sdc` abort, a crash after the redirect opened.
  You are the one who watched it run. Supplying it is itself the declaration of failure, so it
  wins over the gate; write the cause you actually read rather than a category, since nothing
  parses it.
- **`--failure-kind`**, which fills `stage_specific.failure_kind`, alongside it: `infra` when
  PrimeTime never ran, `tooling` when it ran and its output is unusable. That is the one thing an
  absent report cannot settle. The third value, `ppa`, is the gate's to write and never yours.
- **`--fix-owner`** on every failure, license failures included, since it is what fills
  `stage_specific.fix_owner`. A `fail_reason` naming the guilty stage in prose while the flag was
  omitted reads to the caller as "this stage could not tell", and brings a human in to re-derive
  an answer you already had. You cannot edit the netlist or the constraints, so the owner is
  never this stage: name the producer of whichever input you read and found wrong, and omit the
  flag only when your own environment broke or you read the evidence and still cannot say.

Exit 0 means written, pass or fail. Exit 2 is BLOCKED and never a `status=fail`: an empty
`--fail-reason`, one without a `--failure-kind`, or a program exception. stderr names which.

## Return Contract

Emit `STATUS: DONE` as your last line once `result.json` exists, or
`STATUS: BLOCKED <one-line reason>` when nothing could be written. What runs next is the
caller's decision, taken from `result.json`.
