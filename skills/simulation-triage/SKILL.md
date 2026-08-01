---
name: simulation-triage
description: Use when a simulation run fails and root-cause analysis is needed before a rework decision; not for fixing code, modifying state, or running regression.
---

# Simulation Triage

The pipeline's graduated root-cause analyzer for a failed simulation run. Reason over the
failure evidence first (**L1**: logs, spec, refmodel, and the failing run's own FSDB waveform),
and only when L1 cannot reach high confidence, run a controlled experiment in scratch to verify
the uncertain conjecture that remains (**L2**). Then land the verdict: a `root_cause` naming the
stage that must act, and a `confidence` that decides whether that verdict is acted on directly
or reaches a human first.

## Iron Rule

- **Canonical read-only, own-workdir writable**: read any canonical artifact freely (RTL, spec, TB
  logs, plan) but never modify another stage's canonical output — RTL, TB, spec, plan, or any
  other stage's `result.json`. The only files you write live under your own `{workdir}`
  (including `{workdir}/experiment/` for L2).
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Artifacts

Read `{workdir}/dispatch.json` first — the kernel writes it at dispatch. Its `inputs` table maps four keys to
absolute cross-stage locations; read those directly and never construct a module-root-relative
`Verification/…` or `Design/…` path yourself. Throughout this skill, `<sim_run>` is shorthand
for the failed-run directory named by that key (and likewise `<design>` / `<rtl>` / `<plan>`).

| Key | What it names | What you read there |
|---|---|---|
| `<sim_run>` | The failed `simulation` **run** directory you are triaging (not that stage's root) | `result.json` — the failing envelope: `stage_specific.failure_phase` / `fail_reason` / `failing_cases[]` / `coverage_gaps[]` + `gaps_not_in_testpoints` / `conformance_findings[]`. Read this copy, not the simulation stage root's: the stage root holds whichever run finished last, so a later passing run overwrites it. Also here: the run's full working area (regression log, per-case UVM logs, coverage DB, KDB), the failing test's `<test_id>.fsdb`, and `tb/uvm/top/<module>_tb_top.sv` — the TB top that names the top-level scope and the DUT instance every FSDB signal path starts from. |
| `<design>` | The `specification` stage root | `design.md` + the per-child `<child>.md` (via `manifest.json`) — spec intent, to judge a spec-vague / RTL / plan discrepancy. |
| `<rtl>` | The `rtl-design` stage root | The `*.v` sources via `rtl-files.json` — the DUT under test. Read for L1 tracing, for the instance hierarchy below the DUT, and, read-only via `` `include``, for L2's experiment leaves. |
| `<plan>` | The `simulation-plan` stage root | `verification-plan.md` (the refmodel/scoreboard's behavioral intent — the golden reference) + `tb-scaffold.json` (the testpoints list, for classifying coverage gaps and keeping an L2 golden semantically consistent with the UVM refmodel). |

The failing test's FSDB is dumped by the sim stage and never promoted: it is gc'd on pass, so
only failing tests retain one. Query it read-only; if it is absent, empty, or truncated, degrade
to log+code reasoning.

You write two things, both under `{workdir}`:

| Path | Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` | This round's routing + advisory verdict (`stage_specific`); written by `finalize`. |
| `experiment/` | Mixed (harness SV/C++, golden model, run log, isolation harnesses) | **L2 only** — the controlled experiment. Never clean it up: these files are the evidence the verdict rests on, and they are referenced by path. |

`result.json` is your entire output surface; there is no separate publish step.

## Workflow

### Classify, and extract the fail-case list

Classify `analysis_state` first, then pull the case inputs.

- **Skip** (either condition triggers `analysis_state: "skipped"` + `skipped_reason`; jump straight to Finalize):
  - `<sim_run>/result.json` is unreadable, or omits `failure_phase` / `fail_reason` → `skipped_reason: "input incomplete: <field>"`.
  - The self-read inputs show no fail case at all (a mistakenly-dispatched scenario where regress / smoke is fully pass, or coverage already 100%) → `skipped_reason: "no fail case to analyze"`.
- **Complete** (`analysis_state: "complete"`): take the case list from whichever shape the envelope actually carries. Branch on which list is present, not on `failure_phase` — every case list is optional, and a `smoke` fail decided by the smoke gate carries only `fail_reason`.
  - `failing_cases[]` → one case per entry, each carrying `error_message` / `log_snippet`. Cross-reference the full per-case log under `<sim_run>` when the envelope's snippet isn't enough.
  - `coverage_gaps[]` → one case per gap bin (already split into `gaps_in_testpoints` / `gaps_not_in_testpoints`).
  - `conformance_findings[]` → one case per gating finding. Its `category` is the reasoning key for L1; there is no log to anchor on.
  - **No case list at all** — a compile failure ran no test, a missing prerequisite never started, and a smoke-gate fail names no cases. Treat `fail_reason` plus the log tail from `<sim_run>` as a single synthetic case, land the `root_cause` from it, and emit it as **one** `advisory.findings[]` entry (`anchor` = the failure location the log tail names, else the `fail_reason` itself; `cases` = the synthetic case). One case is one finding here as in every branch above, so a high-confidence verdict always carries a concrete locus (schema-enforced: `high` ⇒ non-empty `findings[]`, each with an `anchor`).

### L1 — reason from logs, spec, refmodel, coverage, and the failing run's FSDB waveform

**Analyze only, do not fix.** Take evidence along the branch you just landed on:

- Log-anchor path (`failing_cases[]`, or the synthetic case): locate the first occurrence of
  `UVM_ERROR` / `UVM_FATAL` / timeout in `failing_cases[i].error_message` / `log_snippet` or in
  `fail_reason`, falling back to the full log under `<sim_run>` when the envelope snippet is
  truncated.
- Coverage path: classify each gap bin by whether it falls inside the scaffold testpoints
  (`gaps_in_testpoints` is pre-split; cross-reference the testpoints list in `tb-scaffold.json`).
- Conformance path: there is no `UVM_ERROR` or gap bin to anchor on. Map each finding's
  `category` to a `root_cause_direction` via the "Conformance category → `root_cause_direction`"
  table in `references/fail-analysis-patterns.md`.

Then query the failing run's FSDB waveform, once the evidence above forms a hypothesis about
which signal and cycle window is suspect. Follow the query protocol in
`references/fail-analysis-patterns.md` ("L1 waveform query"): one signal per invocation,
slash-form paths rooted at the TB top, and read the tool's own warnings before you trust an empty
report. Fold the returned time/value table into the forward analysis as fact — this is L1's own
factual reinforcement (observing the real run), the same class as reading a log line or a line of
RTL, not a new tier.

Land the verdict from what you now have:

- Classify the fault type and `root_cause_direction` per the classification table in
  `references/fail-analysis-patterns.md` (including the coverage-gap row).
- Compare the expected behavior in `verification-plan.md` / `design.md` against the observed
  evidence to trace the discrepancy (only when both carry enough context).
- Cluster cases by root cause (per the clustering guide in the same reference): apply the
  clustering signals — same file / line, same anomalous signal, same TB component, same trigger
  condition. When same-origin cannot be established, leave each case on its own. A cluster's
  cases must share fault type and `root_cause_direction`; disagreement means separate clusters.
- Attribute each cluster per the `root_cause_direction → stage` mapping, then land the top-level
  `root_cause` by its max-case-coverage + tiebreak rule. Cite each finding's `anchor` as file and
  line: it is the locus the rework lands on, so "somewhere in the datapath" is not usable.
- Land `confidence` per the "Confidence (gating)" section of the reference. Most failures resolve
  here: if it is `high`, go straight to Finalize.

### L2 — controlled experiment, when L1 could not reach high confidence

`confidence` is not a qualifier on your prose; it decides what happens to the verdict. A `high`
verdict is acted on directly, `medium` / `low` reaches a human first. That asymmetry is why this
tier exists, and why forcing a `high` to skip it puts an unproven attribution straight into
somebody's code. If L1 could not land `high`, either run the experiment below or land
`medium` / `low` honestly — those are the correct verdict when the evidence genuinely supports
more than one explanation.

- **Trigger:** enter L2 only when L1, including its FSDB waveform query, cannot land
  `confidence: "high"` — per the "L2-trigger judgment" in
  `references/fail-analysis-patterns.md` (competing hypotheses / cannot localize / locus in
  doubt). A single case with a clean log anchor and no plausible alternative explanation skips L2
  entirely.
- **Run a controlled experiment** under `{workdir}/experiment/` to verify the uncertain conjecture L1 left standing — not a rebuild of the real run to characterize it, since that characterization-by-observation already happened in L1, via its FSDB. Drive stimulus the real run never exercised: a hand-chosen input (not a regression vector), an isolation micro-harness that re-instantiates the DUT's leaf modules and taps internals via SV hierarchical references to pin the fault to a specific function or cell, a hand-built golden model kept semantically consistent with the `<plan>`-root UVM refmodel/scoreboard (a small standalone golden is fine as long as its behavior matches; it need not embed UVM components), or a parametric sweep. Pick a tool yourself (Verilator has worked well: fast, cycle-accurate, and hierarchical references make internal taps easy) or a controlled re-run. **Keep observing your own controlled run**: drive a per-cycle **TEXT** dump of it, or another self-owned dump. The failing run's own FSDB cannot see stimulus your controlled run alone drives, so L2 observes its own run rather than relying on it. Canonical RTL is read-only `` `include`` material throughout — never copy-and-edit it.
- **Budget:** at most 2 iteration rounds.
- **Optional:** a single-session blind/adversarial self-check (reason the same evidence twice, once trying to confirm and once trying to refute) to harden the verdict before landing it. Never spawn a sub-Task for this; triage stays a leaf.
- Persist every experiment artifact (harness, golden model, run log, isolation harnesses); never clean up, even after landing the verdict.

L2's evidence may sharpen the `root_cause` L1 landed — confirm which of two competing directions
is real, say — but it does not change the attribution rule.

### Finalize

Assemble the analysis judgment (shape below). `waveform` is present when the `fsdbreport` query
ran; `experiment` is present when, and only when, L2 ran — its presence is what says the verdict
is L2-backed, so there is no separate tier label to set.

```jsonc
{
  "analysis_state": "complete",
  "root_cause": "rtl-design",
  "confidence": "high",
  "advisory": {
    "findings": [ { "anchor": "file:line", "cases": ["…"] } ],
    "waveform": {
      "commands": ["fsdbreport <sim_run>/<test_id>.fsdb -s /tb_top/u_dut/sig -bt 40ns -et 80ns -of h -o w.txt"],
      "signals": ["/tb_top/u_dut/sig"]
    },
    "experiment": {
      "tool": "verilator",
      "stimulus": "<hand-chosen input(s) / sweep the real run never drove>",
      "artifacts": ["experiment/tb_wrap.sv", "experiment/sim_main.cpp", "experiment/golden.py", "experiment/run.log"],
      "golden": "<golden model description or path>"
    }
  }
}
```

Every `experiment.artifacts[]` entry is a real workdir-relative path, resolved as written; do not
abbreviate one. Nest `findings` / `waveform` / `experiment` under `advisory`, never at the top
level. The `skipped` shape carries only `analysis_state: "skipped"` + `skipped_reason`, no
`advisory`.

Run `finalize` to schema-gate the judgment and atomically write `{workdir}/result.json`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simtriage/__main__.py finalize \
  --workdir {workdir} --module {module} \
  --json-file <path to the analysis JSON you assembled>   # or --json-stdin
```

On non-zero exit, read stderr and act: exit 1 = schema violation in your judgment (fix the
content and re-run — this is the authoritative gate for the routing contract); exit 2 = a program
exception (`STATUS: BLOCKED`, never a decision you choose — an input you cannot analyze is
`analysis_state: "skipped"`, decided in the first phase). Exit 0 means `{workdir}/result.json` is
landed.

## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or `STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write).
