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

Reasoning aid for classifying each case; surfaced in the `## Findings` prose (free-text), not as validated fields.

| Fault category | `fault_type` | Typical symptom | `root_cause_direction` | How to trace |
|---|---|---|---|---|
| Compile error | `compile_error` | `make simv` fails | `tb` | Read the compile log; locate the offending line number. |
| Data mismatch | `data_mismatch` | Checker reports expected vs. actual differ | `rtl-design` (or `tb` refmodel) | Compare refmodel against RTL output; trace the differing signal back to its source. |
| Timeout | `timeout` | Simulation hangs; no `finish` | `rtl-design` or `tb` | Check whether the driver issued stimulus and whether the monitor saw a response. |
| UVM fatal | `uvm_fatal` | phase / factory error | `tb` | Read the UVM error message; check component registration and connections. |
| Assertion failure | `assertion_failure` | SVA / immediate assert fired | `rtl-design` | Locate the assertion; analyze the signal state at firing time. |
| Randomization conflict | `randomization_conflict` | randomization failed | `tb` | Inspect the constraint block; simplify or relax constraints. |
| Coverage gap | `coverage_gap` | `gaps_in_testpoints` / `gaps_not_in_testpoints` non-empty | `rtl-design` (gap inside testpoints but RTL unreachable) / `tb` (gap outside testpoints — plan is missing a testpoint) / `specification` (the coverage dimension itself is missing from the requirements) | Check whether the gap bin lives under `scaffold-specification.json.testpoints[].bins[]`. Not there → plan problem. There but `stimulus_iterate` is exhausted → RTL dead code or a spec-level missing dimension. |

## Conformance `category` → `root_cause_direction` (failure_phase=conformance)

Conformance findings carry a reviewer-assigned `category` (not a log symptom). Map each to a
`root_cause_direction`, then apply the same clustering + top-level selection + tiebreak as
the other phases.

| `category` | `root_cause_direction` | Rationale |
|---|---|---|
| `missing` / `wrong-behavior` / `fake-green` | `tb` (scaffold mistake) → stage `simulation` | env authored an inadequate check; there is no in-skill fix-loop. |
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

Use this as the default classification. Deviate only with sufficient justification, and record the reason in ANALYSIS.

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

The Symptom table above is the observed-symptom lens; the same four buckets are also reachable by **where the fix lands**. The one disambiguation it adds (not already crisp above): a fix confined entirely to `tb/uvm/**` scaffold/glue, needing no `verification-plan.md` / `scaffold-specification.json` change → `simulation` (rare — simulation usually absorbs this in its own scaffold-repair budget and never escalates); a fix that changes the plan-prescribed behavior → `simulation-plan`. (rtl-design and specification are already covered by the Symptom rows — not repeated here.)

## Confidence

Drives the confidence qualifier in the `## Root cause` prose (not a validated field).

- `high` — ≥2 cases with matching fault type plus a clear evidence anchor (log path: line / signal / `UVM_ERROR` text; coverage path: gap-bin-to-testpoints relationship is unambiguous).
- `medium` — single-case inference or moderate evidence.
- `low` — no clear anchor / multiple explanations coexist (e.g., `gaps_in_testpoints` could reflect either RTL unreachability or insufficient stimulus).
