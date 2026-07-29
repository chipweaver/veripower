# `inlined_check_hints[]` handling rules

`scaffold-specification.json.testpoints[].inlined_check_hints[]` is the field where the
simulation-plan stage inlines the precise check semantics from the authored check hints
directly into the testpoint (field description: `skills/simulation-plan/references/scaffold-specification.schema.json`). When
materializing the TB / writing the refmodel and scoreboard, you MUST follow the
rules below and are **not allowed** to silently downgrade to shadow-register mode or
mismatch-as-uvm_info mode:

**Derive the golden model from the plan, never from the RTL.** Every cycle-accurate refmodel /
scoreboard check is authored from the testpoint's `implementation_detail` formula + `observable` /
`reference_rule` (and the testpoint's own `intent` for empty-hint testpoints) -- NOT by reading
the DUT RTL. A golden model reverse-engineered from the DUT mirrors the implementation (bugs
included) and can never disagree. If a hint's `implementation_detail` is insufficient to author the
check without consulting the RTL, that is an upstream plan gap -> emit the boundary-case
`STATUS: BLOCKED scaffold-specification.json testpoints[].inlined_check_hints[] incomplete: <TP-ID list>`,
not a license to read the RTL.

- For each testpoint with a **non-empty** `testpoint.inlined_check_hints[]`, the refmodel /
  scoreboard MUST generate cycle-accurate checks for every inlined check. Pick the implementation by
  `implementation_detail` shape:
  - **Assignment-formula shape** (e.g., `wb_ack_o = wb_cyc_i & wb_stb_i & ~wb_ack_o & int_ack`) → in
    the refmodel, translate to `assign exp_<sig> = <expr>;` (or an equivalent always block); the
    scoreboard uses `===` 4-state equality to compare against the DUT pin **on every clk edge**.
  - **Behavioral-description shape** (e.g., `the shift register shifts on every rising edge of
    sd_clk_o`) → implement a cycle-accurate behavioral model in the refmodel + DUT-signal comparison.
  - **Algorithmic shape** (e.g., `7-bit LFSR` / `16-bit CRC ×4 channels`) → implement the reference
    algorithm in the refmodel + output comparison.
  - **Error-trigger-condition shape** (e.g., `timeout triggers CTE`) → scoreboard time-domain
    monitoring of the trigger condition pin / status bit.
- Mismatch handling:
  - Mismatches MUST use `` `uvm_error ``, and the scoreboard's `fail_count` / `mismatch_count` MUST
    actually increment.
  - **Forbidden**: mismatch-as-uvm_info mode (loopholes like "only logged at info level"):
    self-admitting comments like "avoid spurious fail" and the equivalent are treated as a Rule A
    semantic error — do not retry; end with `STATUS: BLOCKED <compile|smoke> <locus>` (the
    orchestrator maps it to the `status=fail` envelope, per `repair-boundaries.md`).
  - Read mismatch and write mismatch are equally strict; loopholes that go beyond plain RW registers
    (clear-on-read / status-bit, etc.) are not allowed.
- The `observable` / `reference_rule` / `latency` / `reset_behavior` fields (if inlined) help select
  signals, look up protocol reference points, set the expected trigger window, and write reset-period
  assertions; when fields are missing, infer from `implementation_detail`.

When `testpoint.inlined_check_hints[]` is **empty** (testpoints created by the LLM during the
sim-plan stage — not derived from the authored check hints but added as scenario-necessary
supplements, e.g., `TP-IRQ` / `TP-RESET` / `TP-CARDET`), you may freely choose a
functional-model mode (shadow register / RM abstraction, etc.); a cycle-accurate refmodel is not
required — this branch covers scenario-class testpoints with no spec formula available at plan time.

**Boundary case fallback (`covers[]` non-empty but `inlined_check_hints[]` empty / missing
`implementation_detail`)**: treat as an upstream simulation-plan contract violation (the sim-plan
stage's coverage-matrix self-check should have caught this case), do NOT
try to fill in the inline content on your own (to avoid silently downgrading by treating a contract
gap as the "free functional choice" branch); instead, end with `STATUS: BLOCKED scaffold-specification.json testpoints[].inlined_check_hints[] incomplete: <TP-ID list>`, so the
orchestrator maps it to `status=fail` + `failure_phase="prerequisite"` and rework goes back to
simulation-plan to fill in the fields.
