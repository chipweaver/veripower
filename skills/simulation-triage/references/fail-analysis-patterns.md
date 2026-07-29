# Fault-analysis pattern reference

## Symptom → `root_cause` mapping

Reasoning aid for landing the top-level `root_cause` (the routing field). These are how you reason to the value, not a serialized schema.

| Symptom | `root_cause` |
|---|---|
| Stimulus matches the specification, but the DUT output is wrong | `rtl-design` |
| Checker / RM / driver / monitor code is inconsistent with the plan | `simulation-plan` (plan is wrong) or `simulation` (simulation modified the scaffold by mistake — rare) |
| The expected behavior the plan prescribes is itself wrong / a scenario is missing / checker semantics are wrong | `simulation-plan` |
| Spec is vague / does not cover the observed scenario | `specification` |
| `gaps_not_in_testpoints` is non-empty (a coverage-hole bin is not under any testpoint) | `simulation-plan` (default; testpoints must be added) |
| `gaps_in_testpoints` is non-empty but the RTL is unreachable (dead code) | `rtl-design` |
| A coverage dimension was never set up (the specification omitted the requirement) | `specification` (rare) |

## `fault_type` and `root_cause_direction` detailed classification

Reasoning aid for classifying each case; surfaced as free-text `fault_type` values inside `advisory.findings[]` (schema: `result.schema.json`, under `stage_specific`) — not a separate enum of their own.

| Fault category | `fault_type` | Typical symptom | `root_cause_direction` | How to trace |
|---|---|---|---|---|
| Compile error | `compile_error` | `make simv` fails | `tb` | Read the compile log; locate the offending line number. |
| Data mismatch | `data_mismatch` | Checker reports expected vs. actual differ | `rtl-design` (or `tb` refmodel) | Compare refmodel against RTL output; trace the differing signal back to its source. |
| Timeout | `timeout` | Simulation hangs; no `finish` | `rtl-design` or `tb` | Check whether the driver issued stimulus and whether the monitor saw a response. |
| UVM fatal | `uvm_fatal` | phase / factory error | `tb` | Read the UVM error message; check component registration and connections. |
| Assertion failure | `assertion_failure` | SVA / immediate assert fired | `rtl-design` | Locate the assertion; analyze the signal state at firing time. |
| Randomization conflict | `randomization_conflict` | randomization failed | `tb` | Inspect the constraint block; simplify or relax constraints. |
| Coverage gap | `coverage_gap` | `gaps_in_testpoints` / `gaps_not_in_testpoints` non-empty | `rtl-design` (gap inside testpoints but RTL unreachable) / `tb` (gap outside testpoints — plan is missing a testpoint) / `specification` (the coverage dimension itself is missing from the requirements) | Check whether the gap bin lives under `tb-scaffold.json.testpoints[].bins[]`. Not there → plan problem. There but `stimulus_iterate` is exhausted → RTL dead code or a spec-level missing dimension. |

## Conformance `category` → `root_cause_direction` (failure_phase=conformance)

Conformance findings carry a reviewer-assigned `category` (not a log symptom). Map each to a
`root_cause_direction`, then apply the same clustering + top-level selection + tiebreak as
the other phases.

| `category` | `root_cause_direction` | Rationale |
|---|---|---|
| `missing` / `wrong-behavior` / `fake-green` | `tb` (plan problem) → stage `simulation-plan` | The simulation stage self-heals these check defects in-stage (its Step-4 conformance-fix loop); a self-locus finding reaches triage only after that in-stage fixer returned `STATUS: BLOCKED` — i.e. it judged the check cannot be made adequate without an upstream/plan change. Route upstream (`simulation-plan`), never back to `simulation` (that is the self-pointing loop the in-stage self-heal exists to avoid). |
| `intent-defect` | `tb` (plan problem) → stage `simulation-plan` | the `inlined_check_hints[]` itself is wrong; fix the plan. |

> `unverifiable-arch` / `unavailable` are advisory and never reach triage (the gate does not
> trip on them). If a finding's prose traces the gap to a vague/missing spec, attribute
> `specification` per the Symptom table — `specification` is reachable by reasoning, not by a
> reviewer category.

## Regression-level classification

| Level | Trigger | Regression scope | Typical scenario |
|---|---|---|---|
| compile-only | Compile / environment fixed | `make simv` passes is enough | Syntax errors, include paths. |
| targeted | TB-side change; RTL untouched | Run only the affected case group | Sequence constraints, checker expected-value corrections. |
| full | RTL logic change | Full regression | Functional bug, datapath, state machine. |

Use this as the default classification. Deviate only with sufficient justification, and record the reason in the landed `result.json`'s `stage_specific.advisory.findings[]`.

## Clustering guide

### Clustering signals

| Signal | Meaning |
|---|---|
| Same RTL file / line number | Multiple cases trace their mismatch to the same block of logic. |
| Same signal anomaly | The actual-value deviation reported by the checker shows the same pattern. |
| Same TB component | Multiple cases fault in the same driver / monitor. |
| Same trigger condition | All happen during reset, all at a boundary value, or all inside a specific timing window. |

### Fallback rule

When you cannot determine whether two failures share a root cause, place each in its own group.

### Multi-bug masking

When several bugs are present at once, some may be masked by more prominent ones. Later analysis rounds will surface the newly-exposed bugs.

## Root-cause attribution

### `root_cause_direction` → stage mapping

```
rtl-design                  → stage: "rtl-design"
tb (plan problem)           → stage: "simulation-plan"
tb (scaffold mistake, rare) → stage: "simulation"
both                        → split into two entries: stage: "rtl-design" + stage: "simulation-plan"
specification               → stage: "specification"
```

### Top-level `root_cause` selection rule

1. Pick the stage that covers the most cases as the overall root cause (the caller uses this to decide the primary repair direction).
2. **Tiebreak:** when multiple stages tie on case count, pick in priority order `rtl-design > simulation-plan > specification > simulation`.

### Fix-scope lens (simulation-plan vs simulation)

The Symptom table above is the observed-symptom lens; the same four buckets are also reachable by **where the fix lands**. The one disambiguation it adds (not already crisp above): a fix confined entirely to `tb/uvm/**` scaffold/glue, needing no `verification-plan.md` / plan-sidecar change → `simulation` (rare — simulation usually absorbs this in its own scaffold-repair budget and never escalates); a fix that changes the plan-prescribed behavior → `simulation-plan`. (rtl-design and specification are already covered by the Symptom rows — not repeated here.)

## L1 waveform query

Step 2 queries the failing run's own FSDB (`<test_id>.fsdb`, inside the `sim_run` directory
`inputs.json` names) once the log/spec/refmodel evidence forms a hypothesis about which signal
and cycle window is suspect — not on every case, and never as a substitute for that evidence.

- **When to query:** the log-anchor path (`regress` / `compile` / `smoke` / `prerequisite`) is
  the common case — a `data_mismatch` or `timeout` anchor names or implies a signal; query it to
  see what the real run actually did. A coverage or conformance case with no signal-level anchor
  usually has nothing to query.
- **How:** `fsdbreport <fsdb> -s /<hier>/<signal> -bt <t0> -et <t1> -of h -o <out>` — hierarchical
  signal paths are **slash-form** (`/tb_top/u_dut/sig`, not dotted); the time window is
  `-bt`/`-et`. Discover the signal hierarchy from the RTL — the sources under the injected `rtl`
  stage root — or fall back to
  `fsdb2vcd <fsdb> -o x.vcd` and grep its `$scope`/`$var` lines for the scope list.
- **Treat the result as (A) fact:** the returned `Time | value` text is a direct observation of
  the real failing run — weigh it the same as a log line or a line of RTL, not as a secondary or
  advisory hint.
- **Degrade on empty/truncated:** a missing, empty, or truncated FSDB (a failing run can truncate
  at the `$fatal` that ended it) degrades this step to log+code reasoning only — it does not
  block Step 2 and is not itself a reason to lower confidence. When the FSDB was expected but is
  absent or unreadable, still record `expected FSDB absent/unreadable — degraded to log+code` in
  `advisory.waveform.observation` (SKILL.md Step 5) so a systemic dump failure is visible rather
  than silently absorbed.

## Confidence (gating)

`confidence` is a **gating** routing field on the landed `result.json`'s `stage_specific`
(schema: `result.schema.json`) — not an advisory qualifier. The kernel records it as-is on
the `diagnosis` event; the disposition **reliability gate** then decides: only `high`
auto-routes to the fix_owner; `medium` / `low` escalate to the
operator instead. Land it per this operable definition:

- `high` — the verdict is authoritative. Reachable two ways:
  - **L1 waveform corroborates**: a single, non-conflicting explanation anchored to clear
    evidence (log path: line / signal / `UVM_ERROR` text, optionally corroborated by an
    `fsdbreport` query against the failing run's own FSDB; coverage path: an unambiguous
    gap-bin-to-testpoints relationship) — no competing hypothesis survives the reasoning in
    Step 2.
  - **L2 experiment confirms**: the controlled experiment's isolation harness / sweep directly
    confirms the fault — pins it to a specific function/cell and reproduces the symptom against
    a refmodel-consistent golden.
- `medium` — a single-case inference or moderate evidence; plausible but not pinned down by
  either an L1 anchor (waveform included) or an L2 experiment.
- `low` — no clear anchor, or multiple explanations coexist (e.g., `gaps_in_testpoints` could
  reflect either RTL unreachability or insufficient stimulus), even after L2.

`medium` / `low` are not a failure of the analysis — they are the honest verdict when the
evidence genuinely supports more than one explanation. Do not force `high` to avoid the
escalation (see SKILL.md Red Flags).

## L2-trigger judgment

Escalate from L1 (including its FSDB waveform query) to L2's controlled experiment (SKILL.md
Step 3) when Step 2's reasoning cannot land `confidence: "high"` for one of these reasons:

- **Competing hypotheses** — two or more `root_cause_direction` candidates remain equally
  plausible from the log/spec/refmodel/waveform evidence alone (e.g., could be a driver bug or
  an RTL bug).
- **Cannot localize** — the evidence anchors to a symptom (a mismatch, a hang) but not to a
  specific file/line/signal, and the FSDB query (if one ran) didn't pin it down either.
- **Locus in doubt** — the case's `root_cause_direction` looks clear, but the assigned stage
  doesn't follow from the coverage-gap / conformance-category default without direct confirmation
  (e.g., a `data_mismatch` that could be either the DUT or the TB refmodel).

When Step 2 triggers L2, Step 3 runs a **controlled experiment** — chosen stimulus (not a
regression vector), an isolation micro-harness, a hand-built golden, or a parametric sweep —
that observes its own controlled run. It is not a rebuild of the real failing run to
characterize it: that observation-by-the-real-run role already lives in L1, via its FSDB.

When none of these apply — a single case with a clean log anchor and no plausible alternative
explanation — land `confidence: "high"` from L1 alone (waveform included) and skip L2. L2's
controlled experiment is the expensive tier; pay for it only when L1 genuinely can't decide.
