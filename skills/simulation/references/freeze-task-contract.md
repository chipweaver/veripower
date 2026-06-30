# freeze-rebuild sub-Task contract (wave 1)

The simulation main thread dispatches **one** Level-1 `Task(run_in_background=True)` — the
freeze child — when the Step-1 classifier returns `verdict=freeze`. Your job: copy the prior
canonical TB verbatim, regenerate only `rtl_filelist.f`, recompile against the current RTL, and
run the smoke suite. You do **not** render a scaffold or fill any TODOs.

## Inputs (paths only — the main thread does not read these bodies)

- `{workdir}` — the shared simulation stage workdir (you are the first writer; the verify child
  runs in the same directory in wave 3).
- `{module}` — module name.
- `{canonical}` — the canonical `Verification/simulation/` directory from the prior promoted run;
  read-only reference (you copy from it, never write to it).
- `{scaffold}` — `Verification/simulation-plan/scaffold-specification.json`; required by the
  `check-materialization` self-gate (`--scaffold` is a required argument for that verb).

## Work

1. **Freeze (copy + rtl_filelist regen)**:

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py freeze \
       --module {module} --workdir {workdir} --canonical {canonical}
   ```

   Copies the TB whitelist from `{canonical}` into `{workdir}` and regenerates `rtl_filelist.f`
   against the current RTL. On non-zero exit, act on the stderr `[sim freeze] <reason>` message
   and end with `STATUS: BLOCKED compile <reason>`.

2. **Compile + smoke**: `make simv` → `make smoke`.

   A compile failure here means the current RTL is incompatible with the frozen TB interface
   (e.g. a port or package name changed). This is the interface safety net. On failure, end
   immediately with `STATUS: BLOCKED compile <locus>` — do **not** edit the TB, there is no
   scaffold-repair budget on this branch.

3. **Freeze-exit completeness self-gate**: before reporting `STATUS: DONE`, run

   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/sim/__main__.py check-materialization \
       --workdir {workdir} --scaffold {scaffold}
   ```

   This is a **presence** gate. The copied TB is expected to pass trivially (no TODOs survive in
   a frozen TB). If it exits non-zero, treat it the same as a compile block: end with
   `STATUS: BLOCKED compile <residual locus>`. Do not retry — a frozen TB that fails presence
   is a data-integrity issue, not a fill gap.

The smoke result is judged by the orchestrator's **deterministic gate** (the smoke run's own
`regression-log.txt` `RESULT` lines / per-test `.status` files in `{workdir}`), **not** by your
self-reported `STATUS:` prose. Report `STATUS: DONE` once `make simv` + `make smoke` have run to
completion and the self-gate exits 0.

## verify-handoff

`sim freeze` copies the promoted `verify-handoff.json` from `{canonical}` into `{workdir}` and
asserts its presence before returning. On a freeze run it is always present — the Wave-3 verify
child consumes the frozen copy as-is. You do **not** re-derive or rewrite `verify-handoff.json`.

## Prohibitions

- **No scaffold render / no TODO fill**: you copy a frozen TB — you author nothing. The only
  non-copied write is the regenerated `rtl_filelist.f` plus compile/smoke outputs.
- **No TB edits**: the frozen TB is immutable. If `make simv` fails against it, end with
  `STATUS: BLOCKED compile <locus>` — do not attempt repairs.
- **No RTL-source reads**: this child authors no RTL; reading RTL sources is outside its scope.
- **No Level-2 dispatch**: do not call the Task tool.
- **No `state.py`**: do not call `state.py` — the parent session owns state transitions.
- Stay inside `{workdir}`: all writes are confined to `{workdir}`. Reading `{canonical}` as a
  read-only copy source is allowed.

## Output

- `{workdir}` contains the frozen TB (copied from `{canonical}`) plus the regenerated
  `rtl_filelist.f`, compile artifacts, and `regression-log.txt` RESULT lines + per-test
  `logs/<test>.status` files from `make smoke`. `verify-handoff.json` is the frozen copy
  (copied by `sim freeze`, not re-derived).
- End the response with `STATUS: DONE` + a single JSON line listing the key files present:

  ```json
  {"frozen": true, "files": ["rtl_filelist.f", "tb/uvm/", "verify-handoff.json", "regression-log.txt", "logs/"]}
  ```

  or `STATUS: BLOCKED compile <locus>` if `make simv` or `sim freeze` fails — the orchestrator
  parses this to classify `failure_phase=compile`. The `<locus>` names the failing entity
  (module, port, package) so the orchestrator can route rework to the RTL editing stage.

  `STATUS: BLOCKED` is a **harness-level** signal, distinct from the `result.json.status` enum
  (`pass`/`fail` only); the orchestrator maps it to `status=fail` + `fail_reason` with
  `failure_phase=compile`.
