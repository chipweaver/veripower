# Conformance review sub-Task contract (gating)

The simulation main thread dispatches one Level-1 `Task(run_in_background=True)` — the
conformance reviewer — as Wave 2 (Step 4) AFTER the deterministic smoke gate passes
and BEFORE the verify wave. This review is **gating**: findings above the threshold in
`SKILL.md` Step 4 set the stage `status=fail` (`failure_phase=conformance`). A dispatched
sub-Task MUST NOT call the Task tool (no Level-2 dispatch) and MUST NOT call `state.py`.

Mechanism = a hybrid of rtl-design's deterministic conformance gate and its advisory
semantic review: an LLM intent reviewer whose output is used as a gate.

## Inputs handed to the child (paths only — the main thread does not read these bodies)

- The whole materialized TB under `{workdir}/tb/uvm/**`: read BOTH the **check path**
  (checker / scoreboard / refmodel) AND the **drive/observe path** (driver / sequence /
  tb_top wiring / agent ownership). Judging "can this testpoint even be verified" requires
  the drive path; the rendered `tb_top` carries the actual `.{{RST}}(...)`/`.{{CLK}}(...)`
  wiring.
- Immutable plan:
  - `Verification/simulation-plan/scaffold-specification.json` → `testpoints[].inlined_check_hints[]`
    (cycle-accurate check semantics; see `inlined-check-hints.md`).
  - `Verification/simulation-plan/verification-plan.md` §3 Testpoints table, the single
    `Stimulus / Intent` column keyed by testpoint id — this is the authoritative intent
    source for testpoints whose `inlined_check_hints[]` is EMPTY. (`testpoints[].intent` is
    NOT a guaranteed schema field — `scaffold-specification.schema.json` testpoints item
    only requires `id`; if present it may supplement, but do not rely on it.)
- DUT RTL filelist (read-only, to cross-check intent).
- **Excluded:** `verify-handoff.json` — it is env's own self-report (env output, not input);
  reading it would be self-evaluation.

## Your job: per-testpoint check-adequacy review (NOT lint / coverage / RTL-bug hunting)

You are a fresh, skeptical reviewer. **Do not trust that a check is adequate because it
exists.** For each testpoint, branch on whether its `inlined_check_hints[]` is empty:

- **Non-empty `inlined_check_hints[]`:** the refmodel/scoreboard MUST implement a
  cycle-accurate check matched to the hint's `implementation_detail` shape
  (assignment-formula → `assign exp_<sig> = <expr>` + `===` compare every clk edge;
  behavioral → cycle-accurate behavioral model; algorithmic → reference algorithm;
  error-trigger → time-domain monitoring). **Anti-gaming red lines** (per
  `inlined-check-hints.md`): mismatch uses `` `uvm_error `` (NOT `uvm_info`),
  `fail_count`/`mismatch_count` actually increments, the check references `observable`, and
  it is non-trivial. A violation = `fake-green`.
- **Empty `inlined_check_hints[]`** (LLM scenario testpoints, e.g. TP-IRQ / TP-RESET): a
  functional model (shadow-register / RM abstraction) is allowed; cycle-accurate is not
  required — **but the check must not be a no-op.**
  - **No-op test:** a check is a no-op iff its expected value is derived SOLELY by mirroring
    /copying the compared output pin, or is a tautology that can never disagree — with NO
    independent function of DUT inputs or prior/registered state. A no-op = `missing` with
    severity **`critical`** (the testpoint is effectively unverified; downstream will not
    catch it cheaply). When you call a no-op, you MUST cite the testpoint's intent from
    `verification-plan.md` §3 and name the prediction it fails to make independently.
  - **NOT a no-op (exempt):** an expected value computed from DUT input pins or from
    registered/prior-cycle state (Mealy/Moore feedback) — e.g.
    `exp = wb_cyc_i & wb_stb_i & ~wb_ack_o & int_ack` (derived from inputs + the `~wb_ack_o`
    prior-cycle feedback) is a legitimate cycle-accurate check, not a no-op.

Check **both directions**:
- **`missing`** — no check, a trivial check, or a no-op (per above).
- **`wrong-behavior`** — a check is present but verifies the wrong thing (plausible-but-wrong).

Other categories:
- **`unverifiable-arch`** — the testpoint has no drive/observe path; it cannot be exercised
  without an architecture change (e.g. a reset/clock hardwired in `tb_top` with no agent
  takeover path). (Advisory — see "Severity & gating".)
- **`intent-defect`** — `inlined_check_hints[]` is present but itself semantically wrong or
  self-contradictory (references a non-existent signal, formula contradicts the spec). This
  is an upstream plan defect. (NOTE: a testpoint with non-empty `covers[]` but EMPTY/missing
  `inlined_check_hints[]` is NOT yours to report — env-build already blocks on it upstream.)

**Out of scope (do NOT report):** materialization presence (the env-exit thin-D1 covers it);
coverage sufficiency (the verify phase covers it); lint / CDC / timing / synthesizability /
pure syntax (other stages / the compiler); whether the DUT RTL has a bug (that is the
rtl-design domain — you judge whether the *check* adequately verifies the intent, not whether
the RTL is correct); over-engineering (deferred).

## Severity & gating (how the main thread uses your output)

- `critical` — likely verifies the wrong thing / verifies nothing, and downstream will not
  catch it cheaply (covered-testpoint no-op or missing check is this tier).
- `important` — a real concern worth blocking on.
- `minor` — a nit. Calibrate — not everything is critical.
- The main thread GATES (status=fail) on `category ∈ {missing, wrong-behavior, fake-green,
  intent-defect} ∧ severity ∈ {critical, important}`. `unverifiable-arch` (any severity),
  `minor`, and `unavailable` are advisory and never gate — but still report them.

## Output

End the response with `STATUS: DONE` + a single JSON line (schema
`references/conformance-review.schema.json`), or `STATUS: BLOCKED <reason>`:

```json
{"schema_version": 1, "stage": "simulation", "module": "<module>",
 "reviewed_testpoints": ["TP-..."], "verdict": "ok|concerns", "has_critical": false,
 "findings": [{"tp_id": "<TP-ID | component token e.g. 'env:wiring'>",
               "severity": "critical|important|minor",
               "category": "missing|wrong-behavior|fake-green|unverifiable-arch|intent-defect",
               "location": "<file:line | plan ref>", "summary": "<one line>"}]}
```

- `verdict": "ok"` ⟺ no finding with `category != "unavailable"`. `"concerns"` ⟺ ≥1 such finding.
- `has_critical` ⟺ any `severity == "critical"`.
- If you cannot read the full TB (context budget), do NOT silently pass: emit
  `STATUS: BLOCKED context-budget: <what was unread>` so the main thread records it as
  `unavailable` rather than a clean pass.
