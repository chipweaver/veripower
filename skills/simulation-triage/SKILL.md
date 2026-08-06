---
name: simulation-triage
description: Use when a simulation run fails and root-cause analysis is needed before a rework decision; not for fixing code, modifying state, or running regression.
---

# Simulation Triage

A simulation run failed and the pipeline cannot tell whose fault it is. You produce one
judgment: whose, how sure, where, and on what evidence. No tool checks that judgment and no
downstream stage re-derives it, so the confidence you land is the only thing standing between a
guess and somebody's rebuild.

## Iron Rule

- **Canonical read-only, own-workdir writable**: read any canonical artifact freely (RTL, spec, TB
  logs, plan) but never modify another stage's canonical output — RTL, TB, spec, plan, or any
  other stage's `result.json`. The only files you write live under your own `{workdir}`.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Artifacts

Read `{workdir}/dispatch.json` first — the kernel writes it at dispatch. Its `inputs` table maps four keys to
absolute cross-stage locations; read those directly and never construct a module-root-relative
`Verification/…` or `Design/…` path yourself. Throughout this skill, `<sim_run>` is shorthand
for the failed-run directory named by that key (and likewise `<design>` / `<rtl>` / `<plan>`).

| Key | What it names | What you read there |
|---|---|---|
| `<sim_run>` | The failed `simulation` **run** directory (not that stage's root) | `result.json`, the failing envelope. Read this copy, not the simulation stage root's: the stage root holds whichever run finished last, so a later passing run overwrites it. The run's whole working area is here too — regression log, per-case UVM logs, coverage DB, the TB it compiled, and any retained waveform. |
| `<design>` | The `specification` stage root | `design.md` and the per-child `<child>.md` it indexes, via `manifest.json`. Read these to judge whether the observed behavior is an RTL defect or an under-specified requirement. |
| `<rtl>` | The `rtl-design` stage root | The sources listed in `rtl-files.json`: the DUT under test, and the instance hierarchy inside it. |
| `<plan>` | The `simulation-plan` stage root | `verification-plan.md` — what the refmodel and scoreboard are supposed to enforce — and `tb-scaffold.json`, which owns the testpoint list a coverage hole is measured against. |

You write `result.json` (schema: `references/result.schema.json`), and, if you build one,
`{workdir}/experiment/`. That is the whole output surface; there is no separate publish step.

## What the failing envelope carries

`failure_phase` and `fail_reason` are always present. Every case list is optional, so branch on
which one is actually there rather than on the phase:

- `failing_cases[]` — one case per entry, each with `error_message` and often a `log_snippet`.
  Read the full per-case log under `<sim_run>` when the snippet is cut short.
- `coverage_gaps[]` — one case per gap bin, already split into `gaps_in_testpoints` and
  `gaps_not_in_testpoints`.
- **Neither.** A compile failure ran no test and a missing prerequisite never started, so there is
  nothing to enumerate. A `smoke` failure also arrives with no case list: the verify child is the
  only thing that produces one, and it has not run yet. And a `conformance` failure carries none by
  design — see below. Take `fail_reason` plus whatever the run left on disk as a single case; it is
  usually already a specific sentence about what went wrong.

A `conformance` failure is the one phase where the envelope deliberately tells you almost nothing.
The check-adequacy review is prose at `<sim_run>/conformance-review.md`, with `BLOCKING` on the
heading of each finding that stopped the round; read it. That this phase reached you at all means
the simulation stage already tried to repair its own checks and judged the defect to lie upstream
of them, so attributing it back to `simulation` returns it to the loop that just gave up.

If `<sim_run>/result.json` is unreadable or missing `failure_phase` / `fail_reason`, or the inputs
show no failure at all, land `analysis_state: "skipped"` with a specific `skipped_reason`. That is
the only way to say you cannot analyze this. `STATUS: BLOCKED` means the program crashed, never
that you decided something.

## Reading the failing run's waveform

The simulation stage dumps a full-hierarchy FSDB per test and deletes it on pass, so a failing
test leaves `<sim_run>/<test_id>.fsdb` behind and a passing one leaves nothing — a coverage-phase
failure, where regression already passed, has no waveform to read. Query it once the logs and the
spec have given you a hypothesis about which signal and which window is suspect:

```bash
fsdbreport <sim_run>/<test_id>.fsdb -s /<dut_top>_tb_top/u_dut/<sig> -bt <t0> -et <t1> -of h -o w.txt
```

Four things about `fsdbreport` are worth knowing before you trust what it prints:

- **One signal per invocation.** It reports the *last* `-s` and drops the rest with no warning and
  no non-zero exit, while truncating the column header past the point where you would notice the
  loss. `-cn` does not widen it, and a `-f` config file rejects bare signal paths. Query one
  signal at a time.
- **Paths are slash-form, never dotted, and rooted at the testbench rather than the DUT.** The
  scaffold names the TB top `<dut_top>_tb_top` and instantiates the DUT as `u_dut`, so a signal
  inside the DUT is `/<dut_top>_tb_top/u_dut/<sig>`; those first two components belong to the
  testbench, which is why the RTL cannot supply them. `<sim_run>/tb/uvm/top/*_tb_top.sv` is the
  top this run actually compiled, and the RTL gives you the hierarchy below `u_dut`.
- **A wrong path fails quietly.** An unmatched signal prints `*WARN* Failed to find the signal`,
  writes an empty report, and exits 0 — indistinguishable from a truncated dump unless you read
  the warning. Read it before concluding the waveform had nothing to say.
- The returned time/value table is a direct observation of the real run; weigh it like a log line
  or a line of RTL. A dump that is genuinely absent or truncated (a run can stop at the `$fatal`
  that ended it) is not by itself a reason to lower confidence.

## Building an experiment

You may build and run a scratch experiment under `{workdir}/experiment/`. That directory is why
the read-only rule is scoped to canonical artifacts rather than to you.

Reach for one when reading the evidence cannot settle whose fault it is. It costs a real slice of
the pipeline's wall clock, and `low` plus a human is a legitimate cheaper answer; that tradeoff
is yours to make. Pick the tool yourself — a lightweight open-source simulator, installed if it is
not already present, or the one the failing run used.

Two constraints, both about making the result usable rather than merely expensive. Canonical RTL
goes in by `` `include`` only, never copied and edited. And a golden model has to agree with what
`verification-plan.md` prescribes: one that quietly disagrees will "confirm" an RTL defect that is
really a plan defect, and a wrong attribution is the one error this stage cannot absorb, because
attribution is its whole product.

Whatever the experiment produces stays at the path you record in `advisory.experiment.artifacts[]`.
Those paths are what the next reader opens, so nothing there is cleaned up.

## Landing the verdict

Every finding carries a `root_cause` — `rtl-design`, `simulation-plan`, `specification`, or
`simulation` — naming the rule that must act on **that** finding. Choosing it is the judgment this
stage exists to make.

A regression fails for as many reasons as it fails for, and a finding can sit in a different
stage's files from its neighbour. Findings are grouped by their cause, each group becomes its own
attribution carrying its own anchors, and every named stage is dispatched. So do not fold several
causes into whichever one is biggest and leave the rest in the prose: an anchor whose stage is
never named is a fix nobody schedules.

That is for genuinely separate causes. When two stages are implicated in **the same** cause and you
cannot tell which is at fault, splitting is the wrong answer and so is picking one — that is what
`confidence: low` is for.

`confidence` is not a hedge on your prose; it decides what happens next, and it has two values
because there are two things that can happen. A `high` verdict is acted on directly. `low` reaches
a human instead, which is the honest answer whenever the evidence supports more than one
explanation, and not a failure of the analysis. Do not reach for `high` to spare someone the
interruption: the interruption is cheaper than a wrong rebuild.

Note what `low` is not saying. It is about the attribution, not the location: you can be certain
where the symptom is and still be unsure whose fault it is, which is why an anchored finding does
not make a verdict `high` on its own.

A `high` verdict also has to be anchored, and the schema enforces it — every finding carrying an
`anchor`, because that `anchor` is the `file:line` the rework starts from. A `complete` analysis
needs at least one finding either way: the findings are where the attribution lives, so an
analysis with none has not said whose fault it is.

## Finalize

```jsonc
{
  "analysis_state": "complete",
  "confidence": "high",
  "advisory": {
    // one entry per finding; findings sharing a root_cause become one attribution
    "findings": [ { "anchor": "file:line", "cases": ["…"], "root_cause": "rtl-design" } ],
    "waveform": {                    // when you queried a dump
      "commands": ["fsdbreport <sim_run>/<test_id>.fsdb -s /<dut_top>_tb_top/u_dut/<sig> -bt 40ns -et 80ns -of h -o w.txt"],
      "signals": ["/<dut_top>_tb_top/u_dut/<sig>"]
    },
    "experiment": {                  // when you built one
      "tool": "<simulator you used>",
      "stimulus": "<what you drove that the real run never did>",
      "artifacts": ["experiment/tb_wrap.sv", "experiment/run.log", "experiment/golden.py"],
      "golden": "<golden model description or path>"
    }
  }
}
```

`findings`, `waveform` and `experiment` nest under `advisory`, never at the top level, and every
`artifacts[]` entry is a real workdir-relative path, resolved as written. The `skipped` shape
carries `analysis_state` and `skipped_reason`, nothing else.

Run `finalize` to schema-gate the judgment and atomically write `{workdir}/result.json`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simtriage/__main__.py finalize \
  --workdir {workdir} \
  --json-file <path to the analysis JSON you assembled>   # or --json-stdin
```

On non-zero exit, read stderr and act: exit 1 is a schema violation in your judgment — fix the
content and re-run; exit 2 is a program exception. Exit 0 means `{workdir}/result.json` is landed.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write).
