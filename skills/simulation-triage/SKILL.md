---
name: simulation-triage
description: Use when a simulation run fails and root-cause analysis is needed before a rework decision; not for fixing code, modifying state, or running regression.
---

# Simulation Triage

The pipeline's authoritative, graduated root-cause analyzer for a failed simulation run:
reason over the failure evidence first (**L1** — logs, spec, refmodel, and the failing run's
own FSDB waveform), and only when L1 can't reach high confidence, run a controlled experiment
in scratch to verify the uncertain conjecture that remains (**L2**) — then land the verdict.
**Canonical read-only, scratch-writable**: free to read any canonical artifact; the only files
you ever write live under your own `Verification/simulation-triage/**`.

The landed `analysis.json` has two tiers:
- **Routing tier** — `analysis_state` + `root_cause` + the gating `confidence`; the hard,
  schema-validated contract `route.py` consumes to pick a rework target or escalate.
- **Advisory tier** (`advisory.{level, fix_direction, findings[], waveform, experiment}`) —
  persisted evidence forwarded to the rework target as `directive`; informs the fix,
  does not gate routing.

## When to Use

- A simulation run just failed and an authoritative root-cause verdict is needed before any rework.
- The caller wants a `root_cause` plus a gating `confidence` to decide whether to auto-route the
  rework or escalate to the operator.

## Iron Rule

- **Canonical read-only, scratch-writable**: read any canonical artifact freely (RTL, spec, TB
  logs, plan) but never modify another stage's canonical output — RTL, TB, spec, plan, or any
  other stage's `result.json`. The only files you write live under your own
  `Verification/simulation-triage/**` (including `runs/<sim_run>/experiment/` for L2).
- L2's experiment harness is new-written scratch, never a copy-and-edit of canonical RTL —
  canonical RTL is `` `include``d read-only throughout, which is what keeps L2 from colliding
  with any other stage's output.
- Both the `runs/<sim_run>/analysis.json` you write and the top-level `analysis.json` you publish
  MUST validate against `references/analysis.schema.json` (contract violation otherwise).
  `root_cause`'s and `confidence`'s legal values are enforced there — do not re-enumerate them here.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{module}` | Module name. |
| `<sim_run>` | The failed `simulation` run number (`Verification/simulation/runs/<sim_run>/`) — the Orchestrator injects it straight from the run it just reaped as `fail`. |

Nothing else is injected — no inline field assembly. You have no `cmd_dispatch`-issued
`{workdir}`; compute your own working area as `Verification/simulation-triage/runs/<sim_run>/`.
Everything besides `{module}` / `<sim_run>` is self-read from canonical disk.

### Self-read from canonical disk

| Path | Use |
|---|---|
| `Verification/simulation/result.json` | Envelope: `stage_specific.failure_phase` / `fail_reason` / `failing_cases[]` / `coverage_gaps[]` + `gaps_not_in_testpoints` / `conformance_findings[]`. |
| `Verification/simulation/runs/<sim_run>/` | The failed run's full working area — regression log, per-case UVM logs, coverage DB, KDB. |
| `Verification/simulation/runs/<sim_run>/<test_id>.fsdb` | The failing test's full-hierarchy FSDB (dumped by the sim stage; not promoted, gc'd on pass — only failing tests retain one). Query it read-only with `fsdbreport` (slash signal paths, `-bt`/`-et` window) for L1's waveform reinforcement (Step 2); if it is absent, empty, or truncated, degrade to log+code reasoning. |
| `Design/specification/design.md` + `<child>.md` (via `manifest.json`) | Spec intent, to judge a spec-vague / RTL / plan discrepancy. |
| RTL sources (via `Design/rtl-design/filelist.txt`) | The DUT under test — read for L1 tracing (incl. FSDB signal-hierarchy discovery) and, read-only via `` `include``, for L2's experiment leaves. |
| `Verification/simulation-plan/verification-plan.md` + `scaffold-specification.json` | The refmodel/scoreboard's behavioral intent (golden reference) and the testpoints list — for classifying coverage gaps and keeping an L2 golden model semantically consistent with the UVM refmodel. |

## Output Artifacts

| Path | Format | Use |
|---|---|---|
| `Verification/simulation-triage/runs/<sim_run>/analysis.json` | JSON (schema: `references/analysis.schema.json`) | This round's routing + advisory verdict. |
| `Verification/simulation-triage/analysis.json` | JSON (same schema) | Latest pointer, atomically published from the `runs/<sim_run>/` copy above; `orchestrate.py decide --analysis <path>` reads this fixed path. |
| `Verification/simulation-triage/runs/<sim_run>/experiment/` | Mixed (harness SV/C++, golden model, run log, isolation harnesses) | **L2 only** — the controlled experiment, persisted for audit (never cleaned up). |

You write no artifact outside `Verification/simulation-triage/**`. This is not a DAG stage: no
`cmd_reap`, no promote, no `result.json` — the two `analysis.json` files above are the entire
output surface.

## Workflow

### Step 1: Classify `analysis_state` and extract the fail-case list

Classify `analysis_state` first; then pull case inputs by `failure_phase`.

- **Skip classification** (any condition triggers `analysis_state: "skipped"` + `skipped_reason`; jump to Step 5):
  - `Verification/simulation/result.json` is unreadable or omits `failure_phase` / the phase-appropriate failure signal → `skipped_reason: "input incomplete: <field>"`.
  - The self-read inputs show no fail case (e.g., a mistakenly-dispatched scenario where regress / smoke is fully pass or coverage already 100%) → `skipped_reason: "no fail case to analyze"`.
- **Complete classification** (`analysis_state: "complete"`): per `failure_phase`, take cases from one of three input shapes:
  - `regress` / `smoke` → cases = `failing_cases[]` (both run UVM test cases; `failing_cases[]` carries `error_message` / `log_snippet` per failing case; cross-reference the full per-case log under `Verification/simulation/runs/<sim_run>/` when the envelope's snippet isn't enough).
  - `compile` / `prerequisite` → no case-level failure list exists (a compile failure has no test runs; a missing prerequisite never started). **Degenerate path:** treat the phase's `fail_reason` plus the compile-log tail (from `runs/<sim_run>/`) as a single synthetic case and describe it directly as the landed `root_cause` — a single synthetic case emits **no** `advisory.findings[]`.
  - `coverage` → no `failing_cases[]` (regress already passed; only coverage is below target). cases = each gap bin in `coverage_gaps[]` (split by `gaps_in_testpoints` / `gaps_not_in_testpoints`); each gap bin is one case and becomes one `advisory.findings[]` entry (a lone gap bin is a single case — as in the degenerate path above).
  - `conformance` → no `failing_cases[]` and no log tail (compile + smoke both passed). cases = each gating finding in `conformance_findings[]`; each finding is one case. Its `category` is the reasoning key for Step 2 — there is no log to anchor on.

### Step 2: L1 — reason from logs, spec, refmodel, coverage, and the failing run's FSDB waveform

(**analyze only, do not fix**; self-read inputs per the tables above):

- Take evidence along the Step 1 branch path:
  - Log-anchor path (`regress` / `compile` / `smoke` / `prerequisite`): locate the first occurrence of `UVM_ERROR` / `UVM_FATAL` / timeout from `failing_cases[i].error_message` / `log_snippet` or `fail_reason` (falling back to the full log under `runs/<sim_run>/` when the envelope snippet is truncated).
  - Coverage path (`coverage`): classify each gap bin by whether it falls inside the scaffold testpoints (`gaps_in_testpoints` is pre-split; cross-reference the testpoints list in `scaffold-specification.json`).
  - Conformance path (`conformance`): there is no UVM_ERROR / gap-bin to anchor. Map each finding's `category` to a `root_cause_direction` via the "Conformance category → `root_cause_direction`" table in `references/fail-analysis-patterns.md`, then cluster + land one top-level `root_cause` per the existing attribution + tiebreak rule.
- **Query the failing run's FSDB waveform** once the evidence above forms a hypothesis about which signal and cycle window is suspect: bare-call `fsdbreport Verification/simulation/runs/<sim_run>/<test_id>.fsdb -s /<hier>/<signal> -bt <t0> -et <t1> -of h -o <out>` (slash-form hierarchical signal paths; discover the hierarchy from the RTL, or fall back to `fsdb2vcd <fsdb> -o x.vcd` and grep its `$scope`/`$var` lines for the scope list). Fold the resulting `Time | value` text into the forward analysis as fact — this is L1's own factual reinforcement (observing the real run), the same class as reading logs/code, not a new tier. On a missing, empty, or truncated FSDB (a failing run can truncate at the `$fatal` that ended it), degrade to log+code reasoning and do not escalate for that reason alone — but when the failing run's FSDB was expected yet is absent or unreadable, record `expected FSDB absent/unreadable — degraded to log+code` in `advisory.waveform.observation` (Step 5) so a systemic FSDB-dump failure stays observable instead of silently degrading forever.
- Classify the fault type and `root_cause_direction` per the classification table in `references/fail-analysis-patterns.md` (including the coverage-gap row).
- Compare the expected behavior in `verification-plan.md` / `design.md` against the observed evidence to trace the discrepancy (only when both carry enough context).
- Cluster cases by root cause (per the clustering guide in `references/fail-analysis-patterns.md`): apply the clustering signals (same file / line, same anomalous signal, same TB component, same trigger condition); when same-origin cannot be established, leave each case on its own. A cluster's cases must share fault type and `root_cause_direction` (disagreement → separate clusters).
- Attribute each cluster per the `root_cause_direction → stage` mapping in `references/fail-analysis-patterns.md`, then land the top-level `root_cause` by its max-case-coverage + tiebreak rule.
- Land an initial `confidence` per the "Confidence (gating)" section in `references/fail-analysis-patterns.md`. Most failures resolve here — proceed straight to Step 4.

### Step 3: L2 gate — controlled experiment when L1 (including its FSDB waveform) can't reach high confidence

- **Trigger:** enter L2 only when Step 2 — including its FSDB waveform query — cannot land `confidence: "high"` — per the "L2-trigger judgment" in `references/fail-analysis-patterns.md` (competing hypotheses / cannot localize / locus in doubt). A single case with a clean log anchor and no plausible alternative explanation skips L2 entirely.
- **Run a controlled experiment** under `Verification/simulation-triage/runs/<sim_run>/experiment/` to verify the uncertain conjecture Step 2 left standing — not a rebuild of the real run to characterize it (that characterization-by-observation now lives in L1, via its FSDB; see Step 2). Drive stimulus the real run never exercised: a hand-chosen input (not a regression vector), an isolation micro-harness that re-instantiates the DUT's leaf modules and taps internals via SV hierarchical references to pin the fault to a specific function or cell, a hand-built golden model kept semantically consistent with the `Verification/simulation-plan` UVM refmodel/scoreboard (a small standalone golden is fine as long as its behavior matches; it need not embed UVM components), or a parametric sweep. Pick a tool yourself (Verilator has worked well — fast, cycle-accurate, and hierarchical references make internal taps easy) or a controlled re-run. **Keep observing your own controlled run**: drive a per-cycle **TEXT** dump of it (or another self-owned dump) — the failing run's own FSDB (`Verification/simulation/runs/<sim_run>/<test_id>.fsdb`, L1's read-only `fsdbreport` evidence from Step 2) cannot see stimulus your controlled run alone drives, so L2 keeps observing its own run rather than relying on it. Canonical RTL is read-only `` `include`` material throughout — never copy-and-edit it.
- **Budget:** ≤ `defaults.yaml:l2_experiment_max_rounds` iteration rounds.
- **Optional:** a single-session blind/adversarial self-check (reason the same evidence twice, once trying to confirm and once trying to refute) to harden the verdict before landing it — never spawn a sub-Task for this; triage stays a leaf.
- Persist every experiment artifact (harness, golden model, run log, isolation harnesses) — never clean up, even after landing the verdict.

### Step 4: Land confidence and `root_cause`

- **`confidence: "high"`** — either L1 alone (optionally corroborated by its FSDB waveform query) gave a single, non-conflicting explanation anchored to clear evidence, or L2's controlled experiment directly confirmed the fault. This is the only case that auto-routes.
- **`confidence: "medium"` / `"low"`** — competing hypotheses remain, or the fault couldn't be localized/pinned down, even after L2. This escalates to the operator via `route.py`'s confidence gate (`triage_low_confidence`) — do not try to force a `high` verdict to avoid the escalation.
- `root_cause` was already landed at the end of Step 2 (Step 3's L2 evidence may sharpen it, e.g. confirm which of two competing directions is real, but does not change the attribution rule itself).

### Step 5: Land the result

Write `Verification/simulation-triage/runs/<sim_run>/analysis.json`:

```jsonc
{
  "analysis_state": "complete",
  "root_cause": "rtl-design",
  "confidence": "high",
  "advisory": {
    "level": "L1",                 // or "L2" when Step 3 triggered
    "fix_direction": "<waveform- or experiment-backed fix direction: file:line + what to change>",
    "findings": [ { "fault_type": "…", "anchor": "file:line", "cases": ["…"] } ],
    "waveform": {                  // present when Step 2's fsdbreport query ran (incl. a degrade note)
      "commands": ["fsdbreport Verification/simulation/runs/<sim_run>/<test_id>.fsdb -s /tb_top/u_dut/sig -bt 40ns -et 80ns -of h"],
      "signals": ["/tb_top/u_dut/sig"],
      "observation": "<what the queried Time|value text showed, or the FSDB-absent degrade note>"
    },
    "experiment": {                // present only when Step 3 triggered
      "tool": "verilator",
      "stimulus": "<hand-chosen input(s) / sweep the real run never drove>",
      "artifacts": ["runs/<sim_run>/experiment/tb_wrap.sv", "…/sim_main.cpp", "…/golden.py", "…/run.log"],
      "golden": "<golden model description or path>",
      "conclusion": "<what the isolation harness / sweep proved, incl. any adversarial self-check>"
    }
  }
}
```

The `skipped` shape carries only `analysis_state: "skipped"` + `skipped_reason` (no `advisory`).

Validate before publishing:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/simtriage/__main__.py validate-analysis \
  --json-file asic/{module}/Verification/simulation-triage/runs/<sim_run>/analysis.json
```

On non-zero exit, read stderr, fix, and re-run — the authoritative gate for the routing contract.
Then atomically publish the top-level pointer (write-temp + rename, same directory):

```bash
cp asic/{module}/Verification/simulation-triage/runs/<sim_run>/analysis.json \
   asic/{module}/Verification/simulation-triage/analysis.json.tmp
mv asic/{module}/Verification/simulation-triage/analysis.json.tmp \
   asic/{module}/Verification/simulation-triage/analysis.json
```

Emit `STATUS: DONE` as the last line. Nothing is returned in the message body — the landed files
are the result.

## Decision Rules

Root-cause selection lives in [`references/fail-analysis-patterns.md`](references/fail-analysis-patterns.md): the symptom/coverage rows, the fix-scope lens (simulation-plan vs simulation), the `root_cause_direction → stage` attribution, the tiebreak, the gating confidence definitions, and the L2-trigger judgment. Land `root_cause` and `confidence` there.

## Red Flags

| Excuse | Reality |
|---|---|
| "I can't fully analyze this — I'll just return `STATUS: BLOCKED`" | Forbidden as a skill decision. Incomplete inputs / no fail case → `analysis_state: "skipped"` + `skipped_reason`. |
| "While I'm in here I'll just fix the bug in the RTL/TB I found" | Analyze and characterize only — writing scratch experiment artifacts under your own `runs/<sim_run>/experiment/` is expected (L2), but never patch canonical RTL/TB/spec/plan. That collapses the analysis/repair separation that makes the caller's routing valid. |
| "L1 is inconclusive but running an experiment is expensive — I'll just call it `high` anyway" | Confidence is a gating field; a forced `high` skips the operator net entirely. If Step 2 (incl. its FSDB waveform query) can't land `high`, either run L2 (Step 3) or land `medium`/`low` honestly. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Lumping every case into one cluster | Cluster strictly by the clustering signals; when same-origin cannot be established, each case stands alone. |
| `fix_direction` too vague | Be specific: file, line, suggested change — for an L2 verdict, ground it in what the isolation harness proved. |
| Putting `level` / `fix_direction` / `findings` / `waveform` / `experiment` at the top level of `analysis.json` | The schema is `additionalProperties: false` at the root — those keys must nest under `advisory`; a top-level placement fails `validate-analysis`. |

## Completion Gate

- [ ] `Verification/simulation-triage/runs/<sim_run>/analysis.json` is written and `simtriage validate-analysis` exits 0 against it (authoritative schema gate).
- [ ] The same content is atomically published to the top-level `Verification/simulation-triage/analysis.json` pointer.
- [ ] `analysis_state` is set (`complete` or `skipped`).
- [ ] When `complete`: `root_cause` and `confidence` are both set; every fail case is reflected in `advisory.findings[]` (a single synthetic/degenerate case needs none).
- [ ] When L2 triggered: `advisory.level == "L2"`, `advisory.experiment` is populated, and `runs/<sim_run>/experiment/` is persisted on disk (not cleaned up).
- [ ] When `skipped`: `skipped_reason` carries a specific reason.
- [ ] No Iron Rule or Red Flag was triggered — nothing outside `Verification/simulation-triage/**` was written.

## Return Contract

The result is landed on disk, not the message body: `Verification/simulation-triage/runs/<sim_run>/analysis.json` plus the atomically-published top-level `Verification/simulation-triage/analysis.json` pointer (schema: `references/analysis.schema.json`). The last line emits `STATUS: DONE`. `STATUS: BLOCKED <reason>` is reserved for the harness fallback when a program exception prevented landing the result; you never choose it.

## Bundled References

- [`references/fail-analysis-patterns.md`](references/fail-analysis-patterns.md) — Symptom/scope → `root_cause`, fault-type / `root_cause_direction` classification, regression-level table, clustering guide, the gating confidence definitions + the L2-trigger judgment, and the root-cause attribution + tiebreak rule.
- [`references/analysis.schema.json`](references/analysis.schema.json) — `analysis.json` schema: routing tier (`analysis_state` / `root_cause` / `confidence`) + advisory tier (`level` / `fix_direction` / `findings[]` / `waveform` / `experiment`).
- `scripts/simtriage/` (the `validate-analysis` verb) — pre-publish self-gate (invocation contract: Step 5 + `--help`; run before publishing the top-level pointer).
- `defaults.yaml` — `l2_experiment_max_rounds`, the L2 iteration budget (Step 3).
