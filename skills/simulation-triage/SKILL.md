---
name: simulation-triage
description: Use when a simulation run fails and root-cause analysis is needed before a rework decision; not for fixing code, modifying state, or running regression. Read-only.
---

# Simulation Triage

Per-case root-cause analysis → cluster grouping → return the triage result. **Read-only** — does not modify any file, does not modify any external state.

The result has two tiers:
- **Routing block** — a small JSON object (the final `ANALYSIS:` block); the hard, schema-validated contract, carrying only `root_cause` + `analysis_state`.
- **Analysis prose** — a structured-markdown section above it; advisory evidence the caller reads to author its rework hint, not schema-validated.

## When to Use

- A simulation failure result already exists and a read-only root-cause analysis is needed before any fix.
- The caller wants a routing attribution (`root_cause`) plus analysis evidence to decide the subsequent repair target.

## Iron Rule

- **read-only**: do not write files, do not modify any external state, do not perform fixes.
- The final `ANALYSIS:` routing block MUST validate against `references/analysis.schema.json` (contract violation). `root_cause`'s legal values are enforced there — do not re-enumerate them here.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{module}` | Module name. |

You write no artifact and have no `{workdir}` concept. External reference inputs are provided entirely as inline content in the caller's dispatch prompt; nothing is read from disk.

### External reference inputs (inline in dispatch prompt)

| Field | Source | Use |
|---|---|---|
| `failure_phase` | `Verification/simulation/result.json.stage_specific.failure_phase` | One of `prerequisite` / `compile` / `smoke` / `regress` / `coverage` / `conformance`. |
| `failure_signal` | Phase-dependent | Log tail / `failing_cases` / `coverage_gaps` plus `gaps_not_in_testpoints` / (conformance) `conformance_findings[]`. |
| `repair_attempts` | Scaffold repairs + stimulus-iterate summary from `Verification/simulation/result.json` | — |
| `sim_plan_summary` | `Verification/simulation-plan/result.json.stage_specific` | — |
| `rtl_summary` | `Design/rtl-design/result.json.stage_specific` | — |

## Output Artifacts

| Output | Format | Use |
|---|---|---|
| Message body: structured-prose analysis, then a final `ANALYSIS:` routing block | prose + JSON (schema: `references/analysis.schema.json`) | Root-cause analysis + routing attribution (no file output). |

You **write no files**; the result is the Task return message body. The caller reads the prose to author its rework hint and extracts the trailing `ANALYSIS:` JSON.

## Workflow

### Step 1: Classify `analysis_state` and extract the fail-case list

Classify `analysis_state` first; then pull case inputs by `failure_phase`.

- **Skip classification** (any condition triggers `analysis_state: "skipped"` + `skipped_reason`; jump to Step 5):
  - The prompt omits `failure_phase` or `failure_signal` → `skipped_reason: "input incomplete: <field>"`.
  - The prompt shows no fail case (e.g., a mistakenly-dispatched scenario where regress / smoke is fully pass or coverage already 100%) → `skipped_reason: "no fail case to analyze"`.
- **Complete classification** (`analysis_state: "complete"`): per `failure_phase`, take cases from one of three input shapes:
  - `regress` / `smoke` → cases = `failing_cases[]` (both run UVM test cases; `failing_cases[]` carries `error_message` / `log_snippet` per failing case; consume the inline content from the prompt, do not read disk).
  - `compile` / `prerequisite` → no case-level failure list exists (a compile failure has no test runs; a missing prerequisite never started). **Degenerate path:** treat the phase's `fail_reason` plus the compile-log tail as a single synthetic case and describe it directly in the `## Root cause` prose — a single synthetic case emits **no** `## Findings`.
  - `coverage` → no `failing_cases[]` (regress already passed; only coverage is below target). cases = each gap bin in `coverage_gaps[]` (split by `gaps_in_testpoints` / `gaps_not_in_testpoints`); each gap bin is one case and becomes one `## Findings` bullet (a lone gap bin is a single case — as in the degenerate path above).
  - `conformance` → no `failing_cases[]` and no log tail (compile + smoke both passed). cases = each gating finding in `conformance_findings[]` (consume the inline content from the prompt); each finding is one case. Its `category` is the reasoning key for Step 2 — there is no log to anchor on.

### Step 2: Per-case root-cause analysis

(**analyze only, do not fix**; inputs come entirely from the prompt, not from disk):

- Take evidence along the Step 1 branch path:
  - Log-anchor path (`regress` / `compile` / `smoke` / `prerequisite`): locate the first occurrence of `UVM_ERROR` / `UVM_FATAL` / timeout from `failing_cases[i].error_message` / `log_snippet` or `fail_reason`.
  - Coverage path (`coverage`): classify each gap bin by whether it falls inside the scaffold testpoints (`gaps_in_testpoints` is pre-split; cross-reference the testpoints list in `sim_plan_summary`).
  - Conformance path (`conformance`): there is no UVM_ERROR / gap-bin to anchor. Map each finding's `category` to a `root_cause_direction` via the "Conformance category → `root_cause_direction`" table in `references/fail-analysis-patterns.md`, then cluster + land one top-level `root_cause` per the existing attribution + tiebreak rule.
- Classify the fault type and `root_cause_direction` per the classification table in `references/fail-analysis-patterns.md` (including the coverage-gap row).
- Compare the expected behavior in `rtl_summary` / `sim_plan_summary` against the observed evidence to trace the discrepancy (only when both carry enough context).
- Note the offending file and line (anchor), a fix suggestion, and the regression level (per the regression-level table).

### Step 3: Cluster by root cause

(per the clustering guide in `references/fail-analysis-patterns.md`):

- Apply the clustering signals (same file / line, same anomalous signal, same TB component, same trigger condition); when same-origin cannot be established, leave each case on its own.
- A cluster's cases must share fault type and `root_cause_direction` (disagreement → separate clusters). This clustering is a **reasoning method** for landing one correct `root_cause` and a calibrated confidence — it is written as prose `## Findings`, not as a serialized array.

### Step 4: Land the top-level `root_cause` and confidence

- Attribute each cluster per the `root_cause_direction → stage` mapping in the "Root-cause attribution" section of `references/fail-analysis-patterns.md`.
- **Top-level `root_cause`** per that section's max-case-coverage + tiebreak rule (the tiebreak priority order is defined there — do not restate it here).
- **confidence** (high/medium/low) per the "Confidence" section there — surfaced as a qualifier in the `## Root cause` prose, not as a separate field.

### Step 5: Emit the result

Write the structured-prose analysis, then on a line by itself the literal prefix `ANALYSIS:` immediately followed by one routing JSON object (the final block). The caller locates the prefix and extracts the JSON.

Before emitting, validate the routing block:

```bash
echo "<json>" | python3 ${CLAUDE_SKILL_DIR}/scripts/simtriage/__main__.py validate-analysis --json-stdin
```

On non-zero exit, read stderr, fix, and re-run — the authoritative gate for the routing contract.

**Message-body shape (`complete`):**

```text
## Root cause
<attributed stage + why + first UVM_ERROR/UVM_FATAL/timeout anchor (or gap-bin↔testpoint relationship); confidence qualifier, e.g. "(high: clear log anchor + recent S-box commit)">

## Findings            (omit when there is a single case)
- <fault type> in <direction>; anchor <file:line>; fix: <hint>; regression: <full|targeted|compile-only>; cases: <a, b>

## Fix hint for rework target
<the one actionable hint the target can't get by re-reading the failure itself>

ANALYSIS:
{ "analysis_state": "complete", "root_cause": "rtl-design" }
```

**Skipped shape** (input incomplete / no fail case — prose is a one-line reason; the routing block carries only the two skip fields):

```text
## Root cause
Skipped: <reason>.

ANALYSIS:
{ "analysis_state": "skipped", "skipped_reason": "input incomplete: failure_phase | no fail case to analyze | ..." }
```

The routing block's required fields and the `complete` / `skipped` discrimination are defined solely in `references/analysis.schema.json` — do not restate them here.

## Decision Rules

Root-cause selection lives in [`references/fail-analysis-patterns.md`](references/fail-analysis-patterns.md): the symptom/coverage rows, the fix-scope lens (simulation-plan vs simulation), the `root_cause_direction → stage` attribution, and the tiebreak. Land `root_cause` there.

## Red Flags

| Excuse | Reality |
|---|---|
| "I can't fully analyze this — I'll just return `STATUS: BLOCKED`" | Forbidden as a skill decision. Incomplete inputs / no fail case → `analysis_state: "skipped"` + `skipped_reason`. |
| "While I'm in here I'll just fix the bug I found" | Analyze only — do not patch. Writing files collapses the analysis/repair separation that makes the caller's routing valid. |

## Pitfalls

| Mistake | Fix |
|---|---|
| Lumping every case into one cluster | Cluster strictly by the clustering signals; when same-origin cannot be established, each case stands alone. |
| Fix hint too vague | Be specific: file, line, suggested change. |
| Putting advisory content into the `ANALYSIS:` JSON | The routing block carries only its schema-defined fields — put analysis evidence in the prose above, not inside the JSON. |

## Completion Gate

- [ ] The message body has the prose analysis, then a final block starting with the literal prefix `ANALYSIS:` immediately followed by a valid JSON object.
- [ ] `simtriage validate-analysis` exits 0 on the emitted routing block (authoritative schema gate).
- [ ] `analysis_state` is set (`complete` or `skipped`).
- [ ] When `complete`: every fail case is analyzed and reflected in the prose (`## Root cause`, and `## Findings` when >1 case); `root_cause` is set per the attribution rule.
- [ ] When `skipped`: `skipped_reason` carries a specific reason.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] **No files were written** (read-only self-check).

## Return Contract

The message body is the structured-prose analysis followed by a final block that starts with the literal prefix `ANALYSIS:` on a line by itself, immediately followed by a valid routing JSON object (schema: `references/analysis.schema.json`). The last line emits `STATUS: DONE`. `STATUS: BLOCKED <reason>` is reserved for the harness fallback when a program exception prevented emitting the result; you never choose it.

## Bundled References

- [`references/fail-analysis-patterns.md`](references/fail-analysis-patterns.md) — Symptom/scope → `root_cause`, fault-type / `root_cause_direction` classification, regression-level table, clustering guide, confidence rules, and the root-cause attribution + tiebreak rule.
- [`references/analysis.schema.json`](references/analysis.schema.json) — ANALYSIS routing-block schema (the sole home for the routing fields + `root_cause` enum).
- `scripts/simtriage/` (the `validate-analysis` verb) — routing-block self-gate (invocation contract: Step 5 + `--help`; run before emitting).
