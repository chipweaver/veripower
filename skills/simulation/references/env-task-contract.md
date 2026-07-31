# env-build sub-Task contract (wave 1)

The simulation main thread dispatches **one** Level-1 `Task(run_in_background=True)` — the
env-build child — as the first of three sequential waves. Your job: bootstrap the stage workdir, fill
the UVM scaffold, compile, and run the smoke suite.

## Inputs (paths only — the main thread does not read these bodies)

- `{workdir}` — the shared simulation stage workdir; you are the first writer, and the verify
  child runs in the same directory in wave 3. On a rework it already holds the previous round's
  TB; on a first run it is empty.
- `{module}` — module name.
- plan-sidecar dir: `<scaffold>/` — holds the two sidecars this stage declares,
  `tb-scaffold.json` (the TB scaffold contract: `agents` / `tests` are materialized into SV
  here, and `testpoints[].inlined_check_hints[]` triggers cycle-accurate refmodel / scoreboard
  checks — see `inlined-check-hints.md`) and `sequences.json` (one seq class per entry).
  `testpoints[].bins[]` is not consumed in this wave, and `power-scenarios.json` is not
  declared here at all — it is power-analysis's.
- verification-plan path: `<plan>/verification-plan.md` — the human-readable
  plan (review anchor for filling intent).
- (rework only) the caller's resolved edit scope, as whichever of these the kernel put in this
  run's `dispatch.json`: `caused_by` (the failing runs' own `result.json` paths — read each, and
  narrow to what it attributes; field names come from that stage's result schema), `scope`
  (module-relative paths or `<file>:<line>` anchors), and `reasons` (a human's judgment on the
  repair, which outranks your own reading of the files). Every path was resolved by the kernel, so
  it exists: read it for CONTENT and do not re-classify readability. On a genuine first run (the
  workdir is freshly bootstrapped with no carried TB), the only reference is the plan.

## Work

1. **Bootstrap + scaffold**:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py bootstrap --module {module} --workdir {workdir} --plan <scaffold>
   ```

   Deploys infrastructure + scaffold to `{workdir}`, including functional sequence placeholders. All
   subsequent `make` targets run with `cd {workdir}`. Always run this step, whether this round is a
   rework or a first run: `bootstrap` is no-clobber — it never overwrites a file already present
   (a carried Makefile / env.sh / filelist.f / tb/uvm / scripts / tests, brought forward by
   `carry_self`), so on a rework it is a no-op over the carried TB, and on a genuinely empty workdir
   it deploys the complete pristine template.
2. **Fill / reconcile scaffold** (bound by **Rule A**, see `repair-boundaries.md`): inside
   `{workdir}`, fill or reconcile every `TODO(` across driver / monitor / checker / RM / functional
   seq / top against the current plan (`verification-plan.md` + the plan sidecars).
   - **First run:** fill every rendered `TODO(` stub in the freshly bootstrapped tree.
   - **Rework (carried TB):** reconcile the carried TB to the current plan, confined to the
     caller's resolved edit scope (whatever `dispatch.json` carried) — change only what that
     scope requires; checks / RM /
     scoreboard already matching the current plan are left byte-identical to the carried baseline.
   All writes happen only in `{workdir}`.
   **Trust the rendered tree.** The bootstrap verb (with `--plan`) renders an atomic, complete, self-describing
   stub tree. Learn structure and fill-conventions from the **rendered stubs and their TODO/header
   comments** (e.g. each stub's `// TODO(...)` states its config_db key, sequencer type, and intent),
   not by reverse-engineering the renderer (sim/scaffold.py). Reading the renderer source is a documented
   **fallback only** — when a stub comment is missing, self-contradictory, or conflicts with the
   observed structure. Do not whole-read `sim/scaffold.py` as a first resort.
   **Reading discipline.** Do not whole-read `tb-scaffold.json` (it is large and the
   first read gets truncated by the token cap, forcing a costly re-read). Instead: take **structural
   facts** (interface signals, txn fields) from the **rendered stubs** (they are already materialized);
   read **check semantics per-testpoint** via `testpoints[].inlined_check_hints[]` (not the whole
   `check_hints` block at once); and read the small top-level arrays
   (`sequences[].agent` / `tests[].seqs` / `rm` / `scoreboard`) for the testpoint→component mapping.
   `testpoints[]` itself carries only `id` / `intent` / `bins` / `covers` / `inlined_check_hints`,
   never agent/seq/rm, so
   the cross-array join is over small arrays. (`verify-handoff.json` is your *output*, not an
   input — it does not exist at fill time.)
3. **Compile + smoke**: `make simv` → `make smoke`. The two steps **share** one
   `defaults.yaml.scaffold_repair_max_rounds` repair budget (compile + smoke do not each get N rounds).
   On a scaffold/wiring error within budget, error-driven repair is allowed (Rule A repairable list);
   on a semantic / expected-behavior error, do **not** retry — end with `STATUS: BLOCKED <one-line
   reason naming compile|smoke + the semantic locus>` so the orchestrator records
   `failure_phase=compile|smoke`. See `uvm-rules.md` for the UVM coding rules the filled scaffold must
   obey.
4. **Env-exit completeness self-gate**: before reporting `STATUS: DONE`, run

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py check-materialization --workdir {workdir} --plan <scaffold>
   ```

   This is a **presence** gate: it fails (non-zero) if any required scaffold SV file is missing
   or any `TODO` marker survives in `tb/uvm/**`. While the scaffold-repair budget remains and the
   gate fails, **keep filling** the residual TODOs/files and re-run it. Only report `STATUS: DONE`
   once it exits 0. If the budget is exhausted and it still fails, end with
   `STATUS: BLOCKED compile <residual TODO/file locus>` (the existing compile mapping; this gate is
   exit-code truth, not narration). It does **not** write `result.json` — the orchestrator's finalize
   run remains the authoritative verdict; this is your self-gate so a hollow TB never
   reaches the wave-3 verify run. (Note: `make smoke` runs earlier in wave 1, *before* this gate —
   the savings are that no regress/coverage wave runs on a hollow TB, not that smoke is skipped.)
   It checks presence and nothing else: a renamed marker, an empty stub or a plausible but
   wrong fill all pass it. Whether a check verifies the right thing is the conformance review's
   question.

The smoke result is judged by the orchestrator's **deterministic gate** (the smoke run's own
`regression-log.txt` `RESULT` lines / per-test `.status` files in `{workdir}`), **not** by your
self-reported `STATUS:` prose. Report `STATUS: DONE` once `make simv` + `make smoke` have run
to completion, the self-gate in Work step 4 exits 0, and the handoff is written; the
smoke gate still decides smoke pass/fail.

## Anti-gaming (cycle-accurate checks)

- Author cycle-accurate checks per `inlined-check-hints.md`: every testpoint with non-empty
  `inlined_check_hints[]` gets a cycle-accurate refmodel / scoreboard check matched to its
  `implementation_detail` shape; mismatches use `` `uvm_error `` with counters that actually
  increment.

## Prohibitions

- **No Level-2 dispatch:** do not call the Task tool.
- **No `kernel.py`:** do not call `kernel.py` — the parent session owns state transitions.
- Stay inside `{workdir}`: all writes confined to `{workdir}` (reading the upstream plan as
  read-only reference is allowed). Do not modify the plan, and do not read or modify
  the RTL source (see the no-RTL-source-read prohibition below; RTL enters only mechanically via the
  compile filelist) — RTL-class issues belong to the RTL editing stage; do not exceed your authority.
- **No RTL-source reads for authoring.** The behavioral reference for every refmodel / scoreboard /
  checker is the sim-plan exit docs (`tb-scaffold.json` `inlined_check_hints[]` +
  the testpoint's `intent`) -- the DUT RTL is NOT in this child's input set and MUST NOT be opened to
  understand a signal or derive an expected value. RTL participates only mechanically, through the
  compile filelist. A golden model reverse-engineered from the DUT mirrors the implementation (bugs
  included) and can never disagree -- circular verification. Reading RTL to author a check is a Rule A
  semantic violation → `STATUS: BLOCKED <compile|smoke> rtl-source-read: <locus>`, do not retry.

## Output

- Write the full TB into the shared `{workdir}`: `Makefile`, `env.sh`, `filelist.f`,
  `tb/uvm/**` (driver / monitor / checker / RM / sequences / top), `scripts/**`,
  `tests/testlist.json`. Not `rtl_filelist.f` — bootstrap derives that one. `make smoke` then
  writes the smoke-suite `regression-log.txt` `RESULT` lines + per-test `logs/<test>.status`
  files: surface these too, since the main-thread smoke gate reads exactly them. These are the
  env-phase artifacts (artifact ownership split is in `artifact-contract.md`); the full-regress /
  coverage / case-result artifacts are produced by the verify child in wave 3, and `result.json`
  is assembled by the orchestrator.
- Emit `{workdir}/verify-handoff.json` — a per-testpoint check-intent digest (schema below) so the
  verify child gets check-intent without re-reading the whole TB.
- End the response with `STATUS: DONE` + a single JSON line listing what is now in the workdir:

  ```json
  {"files": ["Makefile", "env.sh", "filelist.f", "rtl_filelist.f", "tb/uvm/", "scripts/", "tests/testlist.json", "regression-log.txt", "logs/", "verify-handoff.json"]}
  ```

  or `STATUS: BLOCKED <reason>` using exactly one of the two reason-string forms below — the
  orchestrator parses this line to classify `failure_phase`, so the wording must match:

  - **Rule A unrepairable** (compile/smoke semantic error per `repair-boundaries.md`):
    `STATUS: BLOCKED <compile|smoke> <locus>` — naming the failing phase first, then the semantic
    locus. Drives `failure_phase=compile|smoke`.
  - **Incomplete `inlined_check_hints[]`** (boundary-case fallback per `inlined-check-hints.md`):
    `STATUS: BLOCKED tb-scaffold.json testpoints[].inlined_check_hints[] incomplete: <TP-ID list>`
    verbatim. Drives `failure_phase=prerequisite` (rework routes back to simulation-plan).

  `STATUS: BLOCKED` is a **harness-level** signal, distinct from the `result.json.status` enum
  (`pass`/`fail` only); the orchestrator maps it to `status=fail` + `fail_reason` with the
  `failure_phase` classified from the form above.

## `verify-handoff.json` schema

A small digest with **one entry per testpoint** you materialized a check for. It carries the
check-intent forward so the verify child can target coverage bins and read failures without
re-reading the full TB body. Shape:

```json
{
  "module": "<module>",
  "testpoints": [
    {
      "tp_id": "<TP-ID, matching tb-scaffold.json testpoints[].id>",
      "asserts": "<one-line description of what this testpoint's check verifies>",
      "seqs": ["<seq-name>→<the bins it targets>", "..."]
    }
  ]
}
```

- `tp_id` — the testpoint id, matching `tb-scaffold.json.testpoints[].id`.
- `asserts` — one line stating what the materialized check verifies (your check-intent in
  plain prose, e.g. `wb_ack_o follows wb_cyc_i & wb_stb_i, compared every clk edge`).
- `seqs` — for each sequence you wired toward this testpoint, `<seq-name>→<bins>` naming the
  `testpoints[].bins[]` it is meant to hit. The verify child uses this for Rule B coverage-bin
  adjudication: mapping an uncovered bin back to the sequence whose stimulus to iterate.

One entry per materialized testpoint; a testpoint with an empty `inlined_check_hints[]` (free
functional-model branch) still gets an entry whose `asserts` states the functional intent.
