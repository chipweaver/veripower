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

`{workdir}/dispatch.json` carries the `inputs` table, and you open almost none of what it points
at: `bootstrap` resolves `<TOP>` from the single `out/<TOP>_syn.v` under the synthesis stage root
and writes every upstream location into `env.sh`, which the `make` targets read from there. The
netlist, the SDC and the SDF are consumed by the tools; VCS back-annotates delays out of the SDF,
which is what makes the SAIF a gate-level one rather than an RTL toggle count.

The one file you open yourself is `<ppa>/ppa.json`, and only when a `power_mw` miss makes you
decide which side of it is wrong. `finalize` reads it for the gate on its own.

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
python3 ${CLAUDE_SKILL_DIR}/scripts/power/__main__.py bootstrap --module {module} --workdir {workdir} [--top <TOP>]
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

### 3. Close

Every run ends here, a non-zero `make` included. `finalize` is the only writer of `result.json`,
and you never hand-assemble the envelope:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/power/__main__.py finalize \
  --workdir {workdir} --module <module> --scaffold <scaffold> [--fix-owner <rule>] \
  [--fail-reason "<cause>" --failure-kind {infra|tooling}]
```

After a clean `make` it judges: it parses each `reports_ptpx/<id>/power_flat.rpt`, reconciles the
total against internal + switching + leakage, and compares `power_mw` against the targets it reads
from `<ppa>/ppa.json` itself — an absent file or dim leaves the dimension ungated, and says so in
`stage_specific.ppa_gate_skipped`, because a pass with nothing to pass against is a different
claim. It records the measurements as `stage_specific.power_by_scenario[]` and
`stage_specific.ppa_actual[]`, a missed target as `stage_specific.violations[]`, the SAIF set as
`stage_specific.saif_artifacts[]`, the VCS identity as `stage_specific.compile_info`, and the data
faults it detected itself — an empty SAIF, an unreadable or irreconcilable report — as
`stage_specific.failures[]`.

The flags carry what the reports cannot:

- **`--fail-reason`**, which fills `stage_specific.fail_reason`, when `make` exited non-zero and
  there is nothing gradeable. Read a **bounded** slice of the failing step's log
  (`gls-compile-log.txt` / `gls-run-log.txt` / `ptpx.log`) — never the whole dump — and write the
  cause you actually read rather than a category, since nothing parses it. Each step prefixes its
  own error with `phase=<compile|run|ptpx>`; carry that phase into the sentence. Supplying the
  flag is itself the declaration of failure, so it skips the gate.
- **`--failure-kind`**, which fills `stage_specific.failure_kind`, alongside it: `infra` when the
  flow never ran (a missing external reference, no license), `tooling` when it ran and its output
  is unusable. That is the one thing an absent report cannot settle. The third value, `ppa`, is
  the gate's to write and never yours.
- **`--fix-owner`** on every failure, since it is what fills `stage_specific.fix_owner`. You read
  the log, so you are the only party that can say whose artifact is at fault, and nothing
  downstream re-derives it. Go by the file the error names: the synthesized netlist or SDF is
  `synthesis`; a TB source under `<tb_env>` is `simulation`; an unresolvable `sequence_ref` or a
  bogus scenario in `<scaffold>/power-scenarios.json` is `simulation-plan`. A `power_mw` miss
  compares a measured value against a target and either side can be wrong, so before naming
  `rtl-design`, read `<ppa>/ppa.json`: a target whose unit disagrees with the number stored in it
  makes a conforming design look over-budget, and no rebuild converges against it — name
  `specification` when the target is what is malformed. Omit the flag when your own environment
  broke, or when you have read both sides and still cannot name an owner: an unnamed owner is how
  a human gets called in, and a guess spends a full rework round on a stage that cannot fix it.

Exit 0 means written, pass or fail. Exit 2 is BLOCKED and never a `status=fail`: an empty
`--fail-reason`, one without a `--failure-kind`, or a program exception. stderr names which.

## Return Contract

Emit `STATUS: DONE` as your last line once `result.json` exists, or
`STATUS: BLOCKED <one-line reason>` when nothing could be written. What runs next is the caller's
decision, taken from `result.json`.
