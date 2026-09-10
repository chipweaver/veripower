# env-build sub-Task contract

The simulation main thread dispatches **one** Level-1 sub-Task, the
env-build child, first of three sequential children. Your job: bootstrap the stage workdir, fill
the UVM scaffold, compile, and run the smoke suite.

## Inputs (paths only; the main thread does not read these bodies)

- `{workdir}`: the shared simulation stage workdir; you are the first writer, and the verify
  child runs in the same directory later. On a rework it already holds the previous round's
  TB; on a first run it is empty.
- `{module}`: the module name.
- `<skill>`: the simulation skill's own base directory.
- plan-sidecar dir `<scaffold>/`: holds the two sidecars this stage declares,
  `tb-scaffold.json` (the TB scaffold contract: `agents` / `tests` are materialized into SV
  here, and `testpoints[].covers[]` names the check hints your refmodel / scoreboard implement;
  see `authoring-checks.md`) and `sequences.json` (one seq class per entry).
  `power-scenarios.json` is not declared here at all: it is power-analysis's.
- verification-plan path `<plan>/verification-plan.md`: the human-readable
  plan (review anchor for filling intent).
- (rework only) the caller's resolved edit scope, as whichever of these the kernel put in this
  run's `dispatch.json`: `caused_by` (the failing runs' own `result.json` paths: read each, and
  narrow to what it attributes; field names come from that stage's result schema), `scope`
  (module-relative paths or `<file>:<line>` anchors), and `reasons` (a human's judgment on the
  repair, which outranks your own reading of the files). Every path was resolved by the kernel, so
  it exists: read it for CONTENT and do not re-classify readability. On a genuine first run (the
  workdir is freshly bootstrapped with no carried TB), the only reference is the plan.

## Work

1. **Bootstrap + scaffold**:

   ```bash
   python3 <skill>/scripts/sim/__main__.py bootstrap --workdir {workdir} --plan <scaffold>
   ```

   Deploys the infrastructure and the scaffold into `{workdir}`, including functional sequence
   placeholders. All subsequent `make` targets run with `cd {workdir}`. Run it every round, rework
   or first run.

   **What it re-renders, and what that leaves you.** Every round it rewrites what the plan and
   `top-io.json` determine — the interface's signal list, the transaction's fields, `tb_pkg.sv`,
   `tb_top.sv`, the filelist, the testlist — and never touches what a round authored: the
   clocking blocks in `<agent>_if.sv`, the env, the checker, the RM, the sequences. So a boundary
   that moved lands on disk and stops exactly where authorship begins, and it does not announce
   itself:

   - **A signal the plan gained** is declared in the interface's regenerated include and connected
     in `tb_top`, and is in none of the clocking blocks or modports you wrote. Nothing warns — the
     compile is green and the new input is simply never driven. Reconciling it is yours.
   - **An agent the plan gained** has its classes rendered and its interface instantiated, while
     the carried `<module>_env.sv` neither builds nor connects it. That compiles green too; the
     self-gate in step 4 is what catches it.

   *Measured on tpu_top with a real filled clocking block: both cases compile with zero errors and
   zero warnings.* So when the scaffold moved, read the plan against what is on disk before you
   fill anything, and reconcile the clocking blocks, the driver and monitor that read them, and the
   env. This is the cost of the deploy not overwriting what a round wrote, and it is the cheaper
   side: a stale clocking block is one round of reconciliation, and a filled checker replaced by a
   stub is a round of authored checks gone.

2. **Fill / reconcile scaffold**: inside
   `{workdir}`, fill or reconcile every `TODO(` across driver / monitor / checker / RM / functional
   seq / top against the current plan (`verification-plan.md` + the plan sidecars).
   - **First run:** fill every rendered `TODO(` stub in the freshly bootstrapped tree.
   - **Rework (carried TB):** reconcile the carried TB to the current plan, confined to the
     caller's resolved edit scope (whatever `dispatch.json` carried), changing only what that
     scope requires; checks / RM /
     scoreboard already matching the current plan are left byte-identical to the carried baseline.
   All writes happen only in `{workdir}`.
   **Trust the rendered tree.** The bootstrap verb (with `--plan`) renders an atomic, complete, self-describing
   stub tree. Learn structure and fill-conventions from the **rendered stubs and their TODO/header
   comments** (e.g. each stub's `// TODO(...)` states its config_db key, sequencer type, and intent),
   not by reverse-engineering the renderer (sim/scaffold.py). Reading the renderer source is a documented
   **fallback only**, for when a stub comment is missing, self-contradictory, or conflicts with the
   observed structure. Do not whole-read `sim/scaffold.py` as a first resort.
   **Reading discipline.** Do not whole-read `tb-scaffold.json` (it is large and the
   first read gets truncated by the token cap, forcing a costly re-read). Instead: take **structural
   facts** (interface signals, txn fields) from the **rendered includes** (`*_signals.svh` / `*_fields.svh`, regenerated from top-io.json every round);
   read **check semantics per-testpoint** through `testpoints[].covers[]`: each check_id is in
   `<check_hints>/check-hints.json`, and the rows it names in `<requirements>/requirements.json`; and
   read the small top-level arrays (`sequences[].agent` / `tests[].seqs` / `rm` / `scoreboard`)
   for the testpoint→component mapping. `testpoints[]` itself carries only `id` / `intent` /
   `covers` / `seqs`, never agent/rm, so the cross-array join is over small arrays.
3. **Compile + smoke**: `make simv` → `make smoke`.
   Repair scaffold/wiring errors and re-run;
   on a semantic / expected-behavior error, do **not** retry: end with `STATUS: BLOCKED <one-line
   reason naming where it stopped and the semantic locus>`, which the orchestrator records
   verbatim as the round's `fail_reason`.
4. **Env-exit completeness self-gate**: before reporting `STATUS: DONE`, run

   ```bash
   python3 <skill>/scripts/sim/__main__.py check-materialization --workdir {workdir} --plan <scaffold>
   ```

   This is a **presence** gate: it fails (non-zero) if any required scaffold SV file is missing,
   if any `TODO` marker survives in `tb/uvm/**`, or if the env never names an agent the plan
   declares. If the gate fails, fill the residual TODOs/files and re-run it. Only report
   `STATUS: DONE` once it exits 0. It does **not** write `result.json`; the orchestrator's finalize
   run remains the authoritative verdict; this is your self-gate so a hollow TB never
   reaches the verify run. (Note: `make smoke` runs earlier in your own step, *before* this gate,
   the savings are that no regress or coverage run happens on a hollow TB, not that smoke is skipped.)
   It checks presence and nothing else: a renamed marker, an empty stub or a plausible but
   wrong fill all pass it. Whether a check verifies the right thing is the check-adequacy review's
   question.

The smoke result is judged by the orchestrator's **deterministic gate** (the smoke run's own
`regression-log.txt` `RESULT` lines / per-test `.status` files in `{workdir}`), **not** by your
self-reported `STATUS:` prose. Report `STATUS: DONE` once `make simv` + `make smoke` have run
to completion, the self-gate in Work step 4 exits 0, and the handoff is written; the
smoke gate still decides smoke pass/fail.

## Anti-gaming (cycle-accurate checks)

- Author cycle-accurate checks per `authoring-checks.md`: every check a testpoint covers gets a
  cycle-accurate refmodel / scoreboard check matched to its `reference_rule`; mismatches use
  `` `uvm_error `` with counters that actually increment.

## Prohibitions

- **No Level-2 dispatch:** do not call the Task tool.
- **No `kernel.py`:** do not call `kernel.py`: the parent session owns state transitions.
- Stay inside `{workdir}`: all writes confined to `{workdir}` (reading the upstream plan as
  read-only reference is allowed). Do not modify the plan, and do not read or modify
  the RTL source (see the no-RTL-source-read prohibition below; RTL enters only mechanically via the
  compile filelist). RTL-class issues belong to the RTL editing stage; do not exceed your authority.
- **No RTL-source reads for authoring.** The behavioral reference for every refmodel / scoreboard /
  checker is the check hints a testpoint covers, the requirements rows they name, and the
  testpoint's `intent` -- the DUT RTL is NOT in this child's input set and MUST NOT be opened to
  understand a signal or derive an expected value. RTL participates only mechanically, through the
  compile filelist. A golden model reverse-engineered from the DUT mirrors the implementation (bugs
  included) and can never disagree -- circular verification. Reading RTL to author a check is a
  semantic violation → `STATUS: BLOCKED <compile|smoke> rtl-source-read: <locus>`, do not retry.

## Output

- Write the full TB into the shared `{workdir}`: `Makefile`, `env.sh`, `filelist.f`,
  `tb/uvm/**` (driver / monitor / checker / RM / sequences / top), `scripts/**`,
  `tests/testlist.json`. Not `rtl_filelist.f`, which bootstrap derives. `make smoke` then
  writes the smoke-suite `regression-log.txt` `RESULT` lines + per-test `logs/<test>.status`
  files: surface these too, since the main-thread smoke gate reads exactly them. These are the
  env-phase artifacts (artifact ownership split is in `artifacts.md`); the full-regress /
  coverage / case-result artifacts are produced by the verify child, and `result.json`
  is assembled by the orchestrator.
- End the response with `STATUS: DONE` + a single JSON line listing what is now in the workdir:

  ```json
  {"files": ["Makefile", "env.sh", "filelist.f", "rtl_filelist.f", "tb/uvm/", "scripts/", "tests/testlist.json", "regression-log.txt", "logs/"]}
  ```

  or `STATUS: BLOCKED <reason>`. The orchestrator passes your reason through verbatim as the
  envelope's `fail_reason`, so it is the whole of what the next reader gets: name where you stopped
  (compile, smoke, or a check hint you could not author from) and the semantic locus, in your own
  words. A check hint whose rule cannot be authored from is specification's defect, not yours — say
  so and name the `check_id`s.

  `STATUS: BLOCKED` is a **harness-level** signal, distinct from the `result.json.status` enum
  (`pass`/`fail` only); the orchestrator maps it to `status=fail` + your reason.
