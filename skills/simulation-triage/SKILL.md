---
name: simulation-triage
description: Use when a simulation run fails and root-cause analysis is needed before a rework decision; not for fixing code, modifying state, or running regression.
---

# Simulation Triage

A simulation run failed and the pipeline cannot tell whose fault it is. You produce one
judgment: whose, where, and on what evidence. No tool checks that judgment and no downstream
stage re-derives it, so what you land is what gets rebuilt.

## Iron Rule

- **Canonical read-only, own-workdir writable**: read any canonical artifact freely (RTL, spec, TB
  logs, plan) but never modify another stage's canonical output — RTL, TB, spec, plan, or any
  other stage's `result.json`. The only files you write live under your own `{workdir}`.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.
## Artifacts

`<skill>` is this skill's own base directory, named on the first line of this file.

Read `{workdir}/dispatch.json` first — the kernel writes it at dispatch. Its `inputs` table maps four keys to
absolute cross-stage locations; read those directly and never construct a module-root-relative
`Verification/…` or `Design/…` path yourself. Throughout this skill, `<sim_run>` is shorthand
for the failed-run directory named by that key (and likewise `<design>` / `<rtl>` / `<plan>`).

| Key | What it names | What you read there |
|---|---|---|
| `<sim_run>` | The failed `simulation` **run** directory (not that stage's root) | `result.json`, the failing envelope. Read this copy, not the simulation stage root's: the stage root holds whichever run finished last, so a later passing run overwrites it. The run's whole working area is here too — regression log, per-case UVM logs, coverage DB, the TB it compiled, and any retained waveform. |
| `<design>` | The `specification` stage root | `design.md` and the per-child `<child>.md` it indexes, via `manifest.json`: the decisions the RTL was to realize. |
| `<requirements>` | The `specification` stage root | `requirements.json`, the engineer's requirements in the engineer's words. Read the rows the failing behaviour bears on to judge whether it is an RTL defect or an under-specified requirement. |
| `<intent>` | The intent container | The intent tree: `brainstorm.md` plus whatever the engineer delivered with it. A requirement row that points at a file here is read there. |
| `<rtl>` | The `rtl-design` stage root | The sources listed in `rtl-files.json`: the DUT under test, and the instance hierarchy inside it. |
| `<plan>` | The `simulation-plan` stage root | `verification-plan.md` — what the refmodel and scoreboard are supposed to enforce — and `tb-scaffold.json`, which owns the testpoint list a coverage hole is measured against. |

You write `result.json` (schema: `references/result.schema.json`), and, if you build one,
`{workdir}/experiment/`. That is the whole output surface; there is no separate publish step.

## What the failing envelope carries

`fail_reason` is always present. The shape of the envelope says which sub-step tripped, so read
what is actually there:

- `failing_cases[]` — one case per entry, each with `error_message` and often a `log_snippet`.
  Read the full per-case log under `<sim_run>` when the snippet is cut short.
- `gaps_in_testpoints[]` / `gaps_not_in_testpoints[]` — the uncovered items, split by whether any
  testpoint claimed them. Regression passed, so there is no waveform to read.
- `<sim_run>/conformance-review.md` carrying a `BLOCKING` heading — the check-adequacy review
  stopped the round. Read it: the envelope deliberately carries none of it. Reaching you at all
  means the simulation stage already tried to repair its own checks and judged the defect upstream
  of them, so attributing it back to `simulation` returns it to the loop that just gave up.
- **None of those.** A compile failure ran no test, a missing prerequisite never started, and a
  smoke failure precedes the only child that produces a case list — so there is nothing to
  enumerate. Take `fail_reason` plus whatever the run left on disk as a single case; it is usually
  already a specific sentence about what went wrong.

If `<sim_run>/result.json` is unreadable or missing `fail_reason`, or the inputs show no failure at
all, land an empty `findings[]` with a specific `reason`. That is the only way to say you cannot
analyze this. `STATUS: BLOCKED` means the program crashed, never that you decided something.

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
  that ended it) is not by itself a reason to doubt what you have.

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

Whatever the experiment produces stays under `{workdir}/experiment/`; `finalize` puts that
directory into `artifacts[]`, so it is promoted and the next reader opens it there. Nothing in it
is cleaned up.

## Landing the verdict

Every finding carries a `root_cause` — `rtl-design`, `simulation-plan`, `specification`, or
`simulation` — naming the rule that must act on **that** finding, its `anchor` is the `file:line`
that rework starts from, and its `reason` is the argument: what you read and what you concluded
from it. Choosing the `root_cause` is the judgment this stage exists to make; the `reason` is what
makes it checkable. This file is the whole account the fix owner is handed, so a reason thin enough
to be taken on trust is a reason it will act on without checking — and an anchor that has since
moved will then be "fixed" wherever it now points. Write the evidence, not a restatement of the
verdict.

Do not fold several causes into whichever one is biggest and leave the rest in the prose. When two
stages are implicated in **the same** cause and the evidence supports either, name the one you find
most likely rather than splitting it. An attribution is acted on iff it names a rule inside
`simulation`'s inputs, and `simulation` itself is not one, so naming it stops the round for a
human.

## Finalize

```jsonc
{
  // one entry per finding; findings sharing a root_cause become one attribution
  "findings": [
    {
      "anchor": "file:line",
      "root_cause": "rtl-design",
      "reason": "what you read and what you concluded from it",
      "cases": ["…"]                 // the failing test_ids this finding explains
    }
  ]
}
```

The no-attribution shape is `{"findings": [], "reason": "<why>"}` and carries nothing else.

Run `finalize` to schema-gate the judgment and atomically write `{workdir}/result.json`:

```bash
python3 <skill>/scripts/simtriage/__main__.py finalize \
  --workdir {workdir} \
  --json-file <path to the analysis JSON you assembled>   # or --json-stdin
```

On non-zero exit, read stderr and act: exit 1 is a schema violation in your judgment — fix the
content and re-run; exit 2 is a program exception. Exit 0 means `{workdir}/result.json` is landed.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write).
