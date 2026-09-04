---
name: power-analysis
description: Use when running gate-level power simulation + PT-PX averaged power analysis (SAIF flow) for PPA gating; not for RTL functional simulation, static timing, or time-resolved waveforms.
---

# Power Analysis

Your sole responsibility: run VCS gate-level simulation against the post-synthesis netlist and the
UVM TB infrastructure to produce one SAIF per power scenario, run PrimeTime PX in averaged mode
over each of them, and close the run through the `power` CLI. You never grade `power_mw` by eye —
`finalize` parses the reports, judges the target, and writes the verdict.

## Iron Rule

- Write only under `{workdir}`. Every injected input location is read-only, as is every other
  stage's output.
- **Scripts are black boxes, never Read their source.** Invoke them per this skill's documented
  command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol
  (stderr, stdout verdict), not the source. Sole exception: debugging a suspected bug in a
  script itself.

## What you read, and what you produce

`<skill>` is this skill's own base directory, named on the first line of this file.

`{workdir}/dispatch.json` carries the `inputs` table, and you open almost none of what it points
at: `bootstrap` resolves `<TOP>` from the single `out/<TOP>_syn.v` under the synthesis stage root
and writes every upstream location into `env.sh`, which the `make` targets read from there. The
netlist, the SDC and the SDF are consumed by the tools; VCS back-annotates delays out of the SDF,
which is what makes the SAIF a gate-level one rather than an RTL toggle count.

The one file you open yourself is `<requirements>/requirements.json`: the rows judged by
`power-analysis` are yours; a row that points at a file under `<intent>/` is read there. A row with a `power_mw` target is compared by `finalize` itself, per
scenario when the row names one; a row without a target is yours to judge from the reports and
declare through `finalize --requirements`.

Three env vars are yours to supply before `make`:

| | |
|---|---|
| `LIB_V` | std-cell Verilog models, linked against the netlist at compile time |
| `LIB_DB` | the Liberty `.db` synthesis linked against — PT maps activity to power through it, so a different library is a different answer |
| `UVM_HOME` | the UVM tree the TB infrastructure was built against |

`env.sh` refuses to run unless all three name readable files, and every target sources it, so a
wrong path stops the run at the first target instead of after the simulation.

Everything under `{workdir}` is produced by the tools you invoke, and `finalize` enumerates it into
`artifacts[]`. Two parts of it are this stage's deliverable:

| | |
|---|---|
| `saif/<id>.saif` | One per scenario, hardlinked to `saif/_dedup/<sequence_ref>.saif`: scenarios that reduce to the same stimulus are simulated once and share the result. |
| `reports_ptpx/<id>/` | `power_flat.rpt` holds the totals the gate parses; `power_hier.rpt` shows where the power went, for whoever has to reduce it; `switching_activity.rpt` says how much of the activity came from the SAIF rather than from tool defaults; `ptpx.log` is that scenario's own log. |

## Workflow

### 1. Deploy

Export the three env vars, then run `bootstrap` to lay down the run scaffold:

```bash
python3 <skill>/scripts/power/__main__.py bootstrap --workdir {workdir} [--top <TOP>]
```

It copies the templates, resolves `<TOP>`, substitutes the upstream locations into `env.sh`,
renders the UVM power test classes from the plan, and verifies the netlist, the TB filelist and the
plan sidecars its render needs. It aborts when `{workdir}` already holds a `Makefile`, since
`make refresh-tests` is how a later plan change reaches the tests. Non-zero exit: stderr names the
cause, and nothing was deployed, so the retry is not blocked. `make` is the interface to everything
it deployed.

### 2. Run

```bash
cd {workdir} && make all >make.out 2>&1
```

`all` is `gls-compile` (which re-renders the power tests and absolutizes the TB filelist first),
then `gls-run` for one SAIF per scenario, then `ptpx`. The redirect keeps multi-thousand-line VCS
and PT logs out of context; every step also tees its own log, which is what you read on a failure.
`make all` outlives the foreground Bash timeout, so launch it detached (`run_in_background=True`)
and stay in this turn until it exits — nothing resumes a subagent when a job it started finishes.

### 3. Close

Every run ends here, a non-zero `make` included. `finalize` is the only writer of `result.json`,
and you never hand-assemble the envelope:

```bash
python3 <skill>/scripts/power/__main__.py finalize \
  --workdir {workdir} [--fix-owner <rule>] \
  [--fail-reason "<cause>"] \
  [--requirements '[{"id": "R-252", "met": true, "actual": "reported only"}]']
```

After a clean `make` it judges: it parses each `reports_ptpx/<id>/power_flat.rpt`, reconciles the
total against internal + switching + leakage, and compares every `power-analysis` row with a
`power_mw` target using the row's own operator — against the named scenario's measurement when the
row names one, against every scenario's otherwise. It records the measurements as
`stage_specific.power_by_scenario[]` and `stage_specific.ppa_actual[]`, one verdict per row as
`stage_specific.requirements[]` (your `--requirements` verdicts folded in for the rows with no
target), the SAIF set as `stage_specific.saif_artifacts[]`, the VCS identity as
`stage_specific.compile_info`, and the data faults it detected itself — an empty SAIF, a gate-level
run that did not report `PASS`, an unreadable or irreconcilable report — as
`stage_specific.failures[]`. It refuses to write an envelope that leaves a `power-analysis` row
unjudged. No row at all means nothing was gated, and the empty `requirements[]` says so.

The flags carry what the reports cannot:

- **`--requirements`**, your verdict on each `power-analysis` row that carries no target.

- **`--fail-reason`**, which fills `stage_specific.fail_reason`, when `make` exited non-zero and
  there is nothing gradeable. Read a **bounded** slice of the failing step's log
  (`gls-compile-log.txt` / `gls-run-log.txt` / `ptpx.log`) — never the whole dump — and write the
  cause you actually read rather than a category, since nothing parses it. Each step prefixes its
  own error with `phase=<compile|run|ptpx>`; carry that phase into the sentence. Supplying the
  flag is itself the declaration of failure, so it skips the gate.
- **`--fix-owner`** on every failure, since it is what fills `stage_specific.fix_owner`. You read
  the log, so you are the only party that can say whose artifact is at fault, and nothing
  downstream re-derives it. Go by the file the error names: the synthesized netlist or SDF is
  `synthesis`; a TB source under `<tb_env>` is `simulation`; an unresolvable `sequence_ref` or a
  bogus scenario in `<scaffold>/power-scenarios.json` is `simulation-plan`. A missed row
  compares a measured value against the engineer's words and either side can be wrong, so before
  naming `rtl-design`, read the row's `verbatim`: name `specification` when the row itself is what
  is malformed. Omit the flag when your own environment
  broke, or when you have read both sides and still cannot name an owner: an unnamed owner is how
  a human gets called in, and a guess spends a full rework round on a stage that cannot fix it.

Exit 0 means written, pass or fail. Exit 2 is BLOCKED and never a `status=fail`: an empty
`--fail-reason`, a `power-analysis` row nobody judged, or a program exception. stderr names which.

## Return Contract

Emit `STATUS: DONE` as your last line once `result.json` exists, or
`STATUS: BLOCKED <one-line reason>` when nothing could be written. What runs next is the caller's
decision, taken from `result.json`.
