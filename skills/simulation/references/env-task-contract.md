# env-build sub-Task contract (wave 1)

The simulation main thread dispatches **one** Level-1 `Task(run_in_background=True)` — the
env-build child — as the first of two sequential waves. Its job: bootstrap the stage workdir, fill
the UVM scaffold, compile, and run the smoke suite. A dispatched sub-Task MUST NOT call the Task
tool (no Level-2 dispatch).

## Shared Iron Rule (both sub-Tasks)

- Do not modify `verification-plan.md` / `scaffold-specification.json` (the plan is a read-only
  external reference for simulation).
- Do not modify RTL (RTL-class issues belong to the RTL editing stage; this stage does not exceed its
  authority).

## Inputs handed to the child (paths only — the main thread does not read these bodies)

- `{workdir}` — the shared simulation stage workdir (the env-build child is the first writer; the
  verify child runs in the same directory in wave 2).
- `{module}` — module name.
- scaffold-specification path: `Verification/simulation-plan/scaffold-specification.json` — the TB
  scaffold contract. `agents` / `sequences` / `tests` are materialized into SV here;
  `testpoints[].inlined_check_hints[]` triggers cycle-accurate refmodel / scoreboard checks (see
  `inlined-check-hints.md`); `testpoints[].bins[]` and `power_scenarios[]` are not consumed in this
  wave.
- verification-plan path: `Verification/simulation-plan/verification-plan.md` — the human-readable
  plan (review anchor for filling intent).
- (rework only) `{rework_trigger}` — the failed stage's canonical `result.json` path; read its
  `stage_specific` (field names per that stage's result schema) to narrow this round's rewrite scope.
  The orchestrator has already pre-gated this path's readability (an unreadable trigger fails fast as
  `failure_phase="prerequisite"` before this child is dispatched), so the child receives the path for
  CONTENT only — it does not re-classify readability.
  If `{orchestrator_context_path}` is also injected, read that sibling fix-scope hint first; it takes
  priority over the trigger content. On the **first-run** branch (the workdir is freshly bootstrapped
  with no prior canonical TB), the only reference is the plan.

## Work

1. **Bootstrap + scaffold**:
   `bash ${CLAUDE_SKILL_DIR}/scripts/bootstrap_simulation.sh --module {module} --workdir {workdir} [--top <TOP>] --plan scaffold-specification.json`
   → deploys infrastructure + scaffold to `{workdir}`, including functional sequence placeholders. All
   subsequent `make` targets run with `cd {workdir}`.
2. **Fill scaffold TODOs** (bound by **Rule A**, see `repair-boundaries.md`): inside `{workdir}`, fill
   in every `TODO(` across driver / monitor / checker / RM / functional seq / top. References are
   selected per the branch handed in above; any prior canonical TB is read-only reference — never
   copied — and all writes happen only in `{workdir}`.
3. **Compile + smoke**: `make simv` → `make smoke`. The two steps **share** one
   `defaults.yaml.scaffold_repair_max_rounds` repair budget (compile + smoke do not each get N rounds;
   the combined count is recorded so the orchestrator can populate `stage_specific.compile_rounds`).
   On a scaffold/wiring error within budget, error-driven repair is allowed (Rule A repairable list);
   on a semantic / expected-behavior error, do **not** retry — end with `STATUS: BLOCKED <one-line
   reason naming compile|smoke + the semantic locus>` so the orchestrator records
   `failure_phase=compile|smoke`. See `uvm-rules.md` for the UVM coding rules the filled scaffold must
   obey.

The smoke result is judged by the orchestrator's **deterministic gate** (the smoke run's own
`regression-log.txt` `RESULT` lines / per-test `.status` files in `{workdir}`), **not** by this
child's self-reported `STATUS:` prose. Report `STATUS: DONE` once `make simv` + `make smoke` have run
to completion and the handoff is written; the gate decides pass/fail.

## Anti-gaming (cycle-accurate checks)

- Author cycle-accurate checks per `inlined-check-hints.md`: every testpoint with non-empty
  `inlined_check_hints[]` gets a cycle-accurate refmodel / scoreboard check matched to its
  `implementation_detail` shape; mismatches use `` `uvm_error `` with counters that actually
  increment.
- **Red Flags** (any of these is a Rule A semantic violation → `STATUS: BLOCKED`, do not retry):
  - "One more retry / loosen the checker and it'll pass" — semantic (checker/scoreboard/RM) errors do
    not converge by retry; the scaffold-repair budget is for wiring errors only.
  - "Suppress the mismatch as `uvm_info` / leave `mismatch_count` flat so it goes green" — fake-green
    is the canonical gaming failure.
  - "Use a functional/shadow-register model instead of the cycle-accurate refmodel" — a testpoint with
    non-empty `inlined_check_hints[]` MUST generate cycle-accurate checks; downgrading to
    register-value comparison is not allowed.

## Prohibitions (fan-out contract echo)

- **No Level-2 dispatch:** this sub-Task MUST NOT call the Task tool.
- **No `state.py`:** the parent session owns state transitions.
- Stay inside `{workdir}`: all writes confined to `{workdir}` (reading the upstream plan + any prior
  canonical TB as read-only reference is allowed). Do not modify the plan or RTL (shared Iron Rule).

## Pitfalls

| Mistake | Fix |
|---|---|
| Bootstrap aborts: existing `Makefile` detected | `bootstrap_simulation.sh` refuses to overwrite a deployed workdir. The orchestrator hands a fresh empty `runs/<N>/` for every run (including rework), so this should not occur; if it does, the workdir was not fresh — stop and report it. |
| Reporting a mismatch with `$fatal` | MUST use `` `uvm_error `` (see `uvm-rules.md`); `$fatal` bypasses the UVM report server, so the regression runner misses the count and the scoreboard terminates early. |

## Output

- Write the full TB into the shared `{workdir}`: `Makefile`, `env.sh`, `filelist.f`,
  `rtl_filelist.f`, `tb/uvm/**` (driver / monitor / checker / RM / sequences / top), `scripts/**`,
  `tests/testlist.json`. `make smoke` then writes the smoke-suite `regression-log.txt` `RESULT`
  lines + per-test `logs/<test>.status` files — surface these too, since the main-thread smoke gate
  reads exactly them. These are the env-phase artifacts (artifact ownership split is in
  `artifact-contract.md`); the full-regress / coverage / case-result artifacts are produced by the
  verify child in wave 2 (it appends the regress `RESULT` lines to the env-written log), and
  `result.json` is assembled by the orchestrator.
- Emit `{workdir}/verify-handoff.json` — a per-testpoint check-intent digest (schema below) so the
  verify child gets check-intent without re-reading the whole TB.
- End the response with `STATUS: DONE` + a single JSON line listing the files written:

  ```json
  {"files": ["Makefile", "env.sh", "filelist.f", "rtl_filelist.f", "tb/uvm/", "scripts/", "tests/testlist.json", "regression-log.txt", "logs/", "verify-handoff.json"]}
  ```

  or `STATUS: BLOCKED <reason>` using exactly one of the two reason-string forms below — the
  orchestrator parses this line to classify `failure_phase`, so the wording must match:

  - **Rule A unrepairable** (compile/smoke semantic error per `repair-boundaries.md`):
    `STATUS: BLOCKED <compile|smoke> <locus>` — naming the failing phase first, then the semantic
    locus. Drives `failure_phase=compile|smoke`.
  - **Incomplete `inlined_check_hints[]`** (boundary-case fallback per `inlined-check-hints.md`):
    `STATUS: BLOCKED scaffold-specification.json testpoints[].inlined_check_hints[] incomplete: <TP-ID list>`
    verbatim. Drives `failure_phase=prerequisite` (rework routes back to simulation-plan).

  `STATUS: BLOCKED` is a **harness-level** signal, distinct from the `result.json.status` enum
  (`pass`/`fail` only); the orchestrator maps it to `status=fail` + `fail_reason` with the
  `failure_phase` classified from the form above.

## `verify-handoff.json` schema

A small digest with **one entry per testpoint** the env child materialized a check for. It carries the
check-intent forward so the verify child can target coverage bins and read failures without
re-reading the full TB body. Shape:

```json
{
  "module": "<module>",
  "testpoints": [
    {
      "tp_id": "<TP-ID, matching scaffold-specification.json testpoints[].id>",
      "asserts": "<one-line description of what this testpoint's check verifies>",
      "seqs": ["<seq-name>→<the bins it targets>", "..."]
    }
  ]
}
```

- `tp_id` — the testpoint id, matching `scaffold-specification.json.testpoints[].id`.
- `asserts` — one line stating what the materialized check verifies (the env child's check-intent in
  plain prose, e.g. `wb_ack_o follows wb_cyc_i & wb_stb_i, compared every clk edge`).
- `seqs` — for each sequence the env child wired toward this testpoint, `<seq-name>→<bins>` naming the
  `testpoints[].bins[]` it is meant to hit. The verify child uses this for Rule B coverage-bin
  adjudication: mapping an uncovered bin back to the sequence whose stimulus to iterate.

One entry per materialized testpoint; a testpoint with an empty `inlined_check_hints[]` (free
functional-model branch) still gets an entry whose `asserts` states the functional intent.
