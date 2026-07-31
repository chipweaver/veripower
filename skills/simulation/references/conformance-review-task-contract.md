# Conformance review sub-Task contract (gating)

The simulation main thread dispatches one Level-1 `Task(run_in_background=True)` — the
conformance reviewer — as Wave 2 (Step 4) AFTER the deterministic smoke gate passes
and BEFORE the verify wave. This review is **gating**: a finding you mark blocking stops the round. Do not call the Task
tool (no Level-2 dispatch) and do not call `kernel.py`.

**Dispatched every round, never skipped.** Nothing carries the previous round's review forward,
so a round whose TB and plan are both unchanged still gets a fresh one. You judge checks against
intent, not RTL correctness, and that judgment never rests on nothing having moved.

Nobody reads your record before the stage acts on it. That is why one field in it is machine
readable and the rest is yours to write.

## Inputs (paths only — the main thread does not read these bodies)

- The whole materialized TB under `{workdir}/tb/uvm/**`: read BOTH the **check path**
  (checker / scoreboard / refmodel) AND the **drive/observe path** (driver / sequence /
  tb_top wiring / agent ownership). Judging "can this testpoint even be verified" requires
  the drive path; the rendered `tb_top` carries the actual `.{{RST}}(...)`/`.{{CLK}}(...)`
  wiring.
- Immutable plan, all of it in `<scaffold>/tb-scaffold.json`'s `testpoints[]`:
  - `inlined_check_hints[]` carries the cycle-accurate check semantics (see
    `inlined-check-hints.md`).
  - `intent` states what the testpoint drives and why. It is a required field of
    `tb-scaffold.schema.json`, and it is the authoritative intent source for a testpoint
    whose `inlined_check_hints[]` is empty.
  - `bins` / `covers` name what it is meant to hit and which authored checks it answers.
- DUT RTL filelist (read-only, to cross-check intent).
- **Excluded:** `verify-handoff.json` — it is env's own self-report (env output, not input);
  reading it would be self-evaluation.

## Your job: per-testpoint check-adequacy review (NOT lint / coverage / RTL-bug hunting)

You are a fresh, skeptical reviewer. **Do not trust that a check is adequate because it
exists.** For each testpoint, hold the check that was written against what the testpoint set
out to verify, and say whether the first would catch the second going wrong.

- **Non-empty `inlined_check_hints[]`:** the refmodel and scoreboard must implement a
  cycle-accurate check matched to the hint's `implementation_detail` shape (assignment
  formula, behavioral model, reference algorithm, or time-domain trigger monitoring; see
  `inlined-check-hints.md`). The anti-gaming lines are there too: a mismatch raises
  `` `uvm_error `` rather than `uvm_info`, the mismatch counter actually increments, and the
  check reads the `observable` it claims to.
- **Empty `inlined_check_hints[]`** (scenario testpoints the plan author added, e.g. TP-IRQ /
  TP-RESET): a functional model is fine and cycle accuracy is not required, but the check
  must not be a no-op.

  **The no-op test is the one piece of this worth stating precisely,** because a no-op reads
  as a real check to anyone skimming. A check is a no-op when its expected value comes solely
  from mirroring the output pin it then compares, or is a tautology that can never disagree,
  with no independent function of DUT inputs or of prior/registered state. An expected value
  computed from input pins or from prior-cycle feedback is not a no-op, however simple:
  `exp = wb_cyc_i & wb_stb_i & ~wb_ack_o & int_ack` is a legitimate check. When you call a
  no-op, quote the testpoint's `intent` and name the prediction the check fails to make on
  its own.

Look both ways: a check can be absent, trivial or a no-op, and it can be present and verify
the wrong thing. The second is the one that survives a skim.

**Out of scope, do not report:** materialization presence (the env-exit self-gate covers it);
coverage sufficiency (the verify phase covers it); lint, CDC, timing, synthesizability or
syntax (other stages and the compiler); whether the DUT RTL has a bug (you judge the check,
not the design); over-engineering. A testpoint with a non-empty `covers[]` and no
`inlined_check_hints[]` is also not yours: env-build blocks on that upstream.

## Blocking

Every finding carries your own call on whether it stops the round, and the gate is exactly
`any(blocking)`. There is no severity word and no category to file it under: those existed so
a table could work out what you already knew, and the table could only ever recover the
answer you had encoded in them.

Block when the testpoint would pass while the behavior it exists to verify is broken. Do not
block for a nit, for a gap you can name but that costs nothing downstream, or for a testpoint
with no drive or observe path at all (say so, non-blocking: the architecture is the fix, and
this round cannot make it). If you find yourself writing prose that describes a real hole and
then marking it non-blocking, one of the two is wrong.

## Output

Write `{workdir}/conformance-review.md` yourself, then end the response with `STATUS: DONE`,
or with `STATUS: BLOCKED <reason>` if you wrote no file. That one file is your entire write
domain: everything else under `{workdir}` is the material you are judging, and you do not
edit it.

One `##` heading per finding, carrying the testpoint, where you found it, and `BLOCKING` as
the last word when it blocks. Under it, prose:

```markdown
# conformance review — <module>

## TP-03  tb/uvm/checker/microgpt_core_scoreboard.sv:49  BLOCKING
The scoreboard compares next_token end to end and probes nothing between. TP-03's intent
asks for the per-stage values, so a fault in any of them reaches next_token or it does not,
and this check cannot tell which.

## TP-14  tb/uvm/checker/microgpt_core_scoreboard.sv:72
The aggregate throughput bound is not separately asserted. The per-step bounds are tighter
and dominate it, so nothing is unverified; noting it because the plan lists it separately.
```

A file with no findings under the title is a clean review, and it is the only way to record
one. The heading is the whole of what a machine reads: the prose is for whoever fixes this,
and nothing parses it. Write the finding, not a classification of it.

If you cannot read the full TB within your context budget, do not silently pass: end with
`STATUS: BLOCKED context-budget: <what went unread>`, and the main thread records that no review
happened rather than that one found nothing.
