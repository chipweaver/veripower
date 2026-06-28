# Per-child RTL sub-Task contract

The rtl-design main thread dispatches one Level-1 `Task(run_in_background=True)` per child in
`manifest.children[]` (including the top-integration child). Every child gets the identical contract
below. Do not call the Task tool (no Level-2 dispatch).

## Inputs handed to the child (paths only — the main thread does not read these bodies)

- Child unit name + its `manifest.children[<self>].rtl_modules[]` list.
- `{workdir}/<child>.md` (full per-child sub-design — you are its sole consumer; self-contained:
  `frontmatter.ports` = injected §1.4.2 cut-edges, `frontmatter.clocks` ⊆ §1.6; the top-integration
  child's §3.1 instantiation map = §1.4.2 restatement).
- `references/coding-rules.md` path + `constraints/<TOP>.{sdc,sgdc}` paths.
- `design.md` path, **read-scope limited to the §1.4.1/§1.4.2/§1.6 tables only** (the main thread passes
  the path and reads nothing): read **§1.4.1 (Top-Level IO) / §1.4.2 (Inter-module Interconnects) /
  §1.6 (Clocks)** — the slices needed for annotations (`create_generated_clock` ← §1.6, `quasi_static`
  ← §1.4.2, `set_case_analysis` ← §1.4.1) and top wiring (§1.4.2). Do **not** read §1.1–1.5 overview or
  §2–§5 detail. **Every child reads §1.4.1** (a top-IO port's owner is not derivable from the manifest,
  so all children read it rather than risk silently dropping a top-IO-derived `set_case_analysis`).

## Prohibitions (read carefully)

- **No whole-design elaboration / smoke compile.** Do NOT run `verilator` / `iverilog` (or any tool)
  over the whole design or over sibling RTL, and do NOT reverse-read an external verification harness
  (a reference top, `Makefile`, or `*_defines` from the verification environment) to make ports line
  up. Author from the `design.md §1.4.1/§1.4.2` / `<child>.md` contract; integration/elaboration correctness
  is verified by downstream verification.
- **Unit child best-effort self-lint only.** A unit child MAY run `verilator --lint-only` on its **own
  module(s)** — a single-module syntax self-check, best-effort (skipped if no linter is present),
  never the whole design or sibling RTL.

## Output

Write your `rtl_modules[]` into one or more `.v`/`.sv` files of your choosing (one file
may hold multiple modules). End the response with `STATUS: DONE` + a single JSON line, or
`STATUS: BLOCKED <reason>` (e.g. `<child>.md §2 Interface incomplete`).

```json
{
  "files":   ["<rel-path>.sv"],
  "incdirs": ["<rel-dir>"],
  "annotations": {
    "sgdc": { "sync_cell": ["<mod>"], "reset_synchronizer": ["<mod>"],
              "set_case_analysis": [{"port": "<port>", "value": 0}], "quasi_static": ["<sig>"] },
    "sdc":  { "create_generated_clock": [{"module": "<m>", "pin": "<p>"}],
              "set_multicycle_path": ["<desc>"], "set_false_path": ["<desc>"] }
  }
}
```

## Annotation rules (read carefully — these feed lint-cdc + synthesis)

- Report **only structures you authored**, using your **real RTL names** (the module
  name you actually wrote, not a design.md placeholder). This is the whole point — `sync_cell -name`
  must match the netlist.
- **Completeness is contract-bound, not best-effort.** Report **every** annotation your owned
  structures imply from the §1.4.1 / §1.4.2 / §1.6 contract you received. An omission is a contract violation,
  not a silent empty list. RTL-true names (`sync_cell`, `reset_synchronizer`) come from your RTL;
  contract-fact categories (`quasi_static`, `set_case_analysis`, `create_generated_clock`) come from
  the §1.4.1 / §1.4.2 / §1.6 you read. Synthesis has no independent backstop for the SDC categories, so an
  omission there is silently lost downstream — do not omit.
  Note: the `sync_cell` / `reset_synchronizer` (and `sdc.create_generated_clock`'s `module`) names you report are checked for **reality** by the
  stage's `check-conformance` gate — a reported name that is not an actual module in your RTL is a
  conformance violation (you will be re-dispatched to fix it), not a silently accepted annotation.
- Which child reports what: a **leaf** child reports its internal synchronizers / generated clocks;
  the **top-integration** child reports cross-domain `quasi_static` + test-control `set_case_analysis`
  (it owns the §1.4.2 interconnect). Empty lists `[]` when a category genuinely has none.
- `incdirs`: list the include dirs your authored files `` `include `` from. You **author your own
  file/include layout** (specification defines RTL modules, not file layout — see this skill's
  Output Artifacts), so you
  are the source of truth for this. Omit the field (or `[]`) only when your files use no `` `include ``
  — that is the genuine "no include dirs" case, not a guess. A child that uses includes but omits
  `incdirs` is a contract violation (the filelist will lack the `+incdir+`; the compile fails
  downstream — do not omit).
