# Per-child RTL sub-Task contract

The rtl-design main thread dispatches one Level-1 `Task(run_in_background=True)` per child in
`manifest.children[]` (including the top-integration child). Every child gets the identical contract
below. Do not call the Task tool (no Level-2 dispatch).

## Inputs (paths only — the main thread does not read these bodies)

- Child unit name + its `manifest.children[<self>].rtl_modules[]` list.
- Your per-child design doc, at the path the main thread hands you from `manifest.children[<self>].doc`
  (the registry SSoT; nothing is copied into `{workdir}`, so never guess a workdir-local path). It is the
  full per-child sub-design and you are its sole consumer, self-contained:
  `frontmatter.ports` = injected `interconnects.json` cut-edges, `frontmatter.clocks` ⊆ `clocks.json`;
  the top-integration child's §3.1 instantiation map wires those same edges.
- `${CLAUDE_SKILL_DIR}/references/coding-rules.md` — the RTL coding rules your files must follow.
- `top-io.json` and `interconnects.json` paths — the boundary and the cut edges. Read them for
  `set_case_analysis` (← `top-io.json`), `quasi_static` (← `interconnects.json`) and top wiring.
- `clocks.json` path (specification workdir) — the clock definitions. Read it for
  `create_generated_clock`: a `"generated": true` entry is a divider/PLL output whose
  `create_generated_clock` pin is YOUR RTL's to name, deliberately deferred by specification. **Every child reads `top-io.json`** (which of its ports are yours is your own doc's frontmatter claim,
  so all children read it rather than risk silently dropping a top-IO-derived `set_case_analysis`).

## Prohibitions (read carefully)

- **Do not reverse-read your interface into existence.** Your ports come from the
  `top-io.json` / `interconnects.json` / `<child>.md §2` contract — never from an external
  verification harness (a reference top, `Makefile`, or `*_defines` from the verification
  environment) reverse-read until they line up. That harness is one author's guess at the
  contract; the contract is the contract, and it is what your siblings were handed too.
  Integration/elaboration correctness itself is verified downstream by lint-cdc.

## Output

Write your `rtl_modules[]` into one or more `.v` files of your choosing (one file
may hold multiple modules). **STRICT Verilog-2001** — no SystemVerilog: not the `.sv`/`.svh`
extension (`rtl-files.schema.json` rejects it, because the kernel's `rtl`
selectors match `*.v` alone), and not SV-only constructs (`logic`/`always_ff`/`always_comb`/
`typedef`/`enum`/`struct`/`interface`/`package`/…) — that half is your discipline, per
`references/coding-rules.md`; no gate decides it. End the response with `STATUS: DONE` + a single JSON line, or
`STATUS: BLOCKED <reason>` (e.g. `<child>.md §2 Interface incomplete`).

```json
{
  "files":   ["<rel-path>.v", "<rel-path>.vh"],
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
  structures imply from the `top-io.json` / `interconnects.json` / `clocks.json` contract you received. An omission is a
  contract violation, not a silent empty list. RTL-true names (`sync_cell`, `reset_synchronizer`) come
  from your RTL; contract-fact categories (`quasi_static`, `set_case_analysis`,
  `create_generated_clock`) come from the sidecars you read. Synthesis has no independent backstop for the SDC categories, so an
  omission there is silently lost downstream — do not omit.
- Which child reports what: a **leaf** child reports its internal synchronizers / generated clocks;
  the **top-integration** child reports cross-domain `quasi_static` + test-control `set_case_analysis`
  (it owns the interconnect). Empty lists `[]` when a category genuinely has none.
- `incdirs`: list the include dirs your authored files `` `include `` from. You **author your own
  file/include layout** (specification defines RTL modules, not file layout — see this skill's
  Output Artifacts), so you
  are the source of truth for this. Omit the field (or `[]`) only when your files use no `` `include ``
  — that is the genuine "no include dirs" case, not a guess. A child that uses includes but omits
  `incdirs` is a contract violation (every downstream filelist is generated from `rtl-files.json`,
  so a missing entry means a missing include path and the compile fails downstream — do not omit).
- **A header you authored belongs in `files[]`, not only in `incdirs`.** The two carry different
  things: `incdirs` names the directory to search, while `files[]` is the set that leaves your run.
  A header left out of `files[]` stays behind in the run directory, so every downstream `` `include ``
  of it resolves to nothing. The Verilog-2001 rule above governs which files may hold your
  **modules**; it does not narrow what you list here.
