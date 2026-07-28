# Plan adequacy review sub-Task contract (gating)

The simulation-plan main thread self-dispatches ONE Level-1 `Task(run_in_background=True)` (a
fresh plan-adequacy reviewer) AFTER `simplan check-scaffold` (structural +
coverage-matrix) passes and BEFORE the user review loop. This review is **gating**:
`coverage` findings at `severity ∈ {critical, important}` BLOCK `status=pass` until resolved;
`adequacy` findings are advisory **must-acknowledge** (surfaced to the user, never block). The
main thread does NOT auto-fix the plan. Do not call the Task tool and do not call `kernel.py`.

## Inputs (paths only — the main thread reads no body)
- `Design/specification/features.json` (the feature spine testpoints trace to)
- `Design/specification/timing-scenarios.json` (one sequence per scenario)
- `Design/specification/design.md` (§1 behavior, §1.4 IO/interconnects, §1.5 waveforms)
  + each `Design/specification/check-hints/<child>.json` —
  the authoritative statement of what must be verified.
- The plan under review: `{workdir}/verification-plan.md` §3 Testpoints table + §4 Power
  Scenarios, and `{workdir}/scaffold-specification.json` (`testpoints[]` with `covers[]` +
  `inlined_check_hints[]`, `skipped_checks[]`).

## Your job: testpoint-adequacy review of the PLAN (NOT TB / RTL / coverage-run)
You are a fresh, skeptical reviewer. **Do not trust that the plan is adequate because the
structural coverage-matrix passed** (that only proves every check_id is covered-or-skipped). Two
lenses:
- **`coverage`** (gating; reference = spec) — does every spec behavior / failure mode / check
  Verification Hint have a real testpoint, and is every `skipped_checks[]` entry's skip genuinely
  justified against the spec (not hiding a real verification need)? A spec behavior with no
  testpoint, or an unjustified skip, is `coverage`.
- **`adequacy`** (advisory must-acknowledge; no reference — judgment) — does each testpoint's check
  strategy actually verify the behavior? Flag vacuous strategies (a `no_predict` / mirror-the-output
  check that can never disagree), or assertions too weak to catch the intended failure.

## Out of scope (do NOT report)
- TB materialization / RTL correctness (downstream `simulation` conformance-review judges TB
  checks vs testpoints; you judge testpoints vs spec); structural coverage-matrix completeness
  (the `simplan check-scaffold` gate already covers it); lint / timing / power; over-engineering.

## Severity & gating
- `critical` — a spec behavior unverified / a check that verifies nothing, downstream won't catch
  cheaply. `important` — a real concern worth blocking on. `minor` — a nit. Calibrate.
- The main thread BLOCKS on `lens == coverage ∧ severity ∈ {critical, important}`; `adequacy`
  (any severity) is must-acknowledge; `unavailable` never blocks — but report them all.

## Output
End with `STATUS: DONE` + a single JSON line (schema `references/plan-review.schema.json`), or
`STATUS: BLOCKED <reason>`:
```json
{"schema_version": 1, "stage": "simulation-plan", "module": "<module>",
 "reviewed_testpoints": ["TP-..."],
 "findings": [{"tp_id": "<TP-ID | 'plan' for a spec-behavior gap tied to no single testpoint>",
               "lens": "coverage|adequacy",
               "severity": "critical|important|minor",
               "location": "<plan ref | design.md / <child>.md §ref>", "summary": "<one line>"}]}
```
- If you cannot read the full plan/spec (context budget), do NOT silently pass: emit
  `STATUS: BLOCKED context-budget: <what was unread>` so the main thread records it as
  `unavailable` rather than a clean pass.
