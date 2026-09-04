# Per-child RTL sub-Task contract

The rtl-design main thread dispatches one Level-1 sub-Task per child in
`manifest.children[]` (including the top-integration child). Every child gets the identical contract
below. Do not call the Task tool: a sub-Task of yours would append no event and sit outside the
kernel's accounting, where nothing could audit it.

## Inputs (paths only — the main thread does not read these bodies)

- `<skill>` — the rtl-design skill's own base directory, handed over by the main thread.
- Child unit name + its `manifest.children[<self>].rtl_modules[]` list.
- Your per-child design doc, at the path the main thread hands you from `manifest.children[<self>].doc`
  (the registry SSoT; nothing is copied into `{workdir}`, so never guess a workdir-local path). It is the
  full per-child sub-design and you are its sole consumer, self-contained:
  `frontmatter.ports` = injected `interconnects.json` cut-edges, `frontmatter.clocks` ⊆ `clocks.json`;
  the top-integration child's §3.1 instantiation map wires those same edges.
- `<skill>/references/coding-rules.md` — the RTL coding rules your files must follow.
- `top-io.json` and `interconnects.json` paths — the boundary and the cut edges. Read them for
  `set_case_analysis` (← `top-io.json`), `quasi_static` (← `interconnects.json`) and top wiring.
- `clocks.json` path (specification workdir) — the clock definitions. Read it for
  `create_generated_clock`: a `"generated": true` entry is a divider/PLL output whose
  `create_generated_clock` pin is YOUR RTL's to name, deliberately deferred by specification.
  **Every child reads `top-io.json`**: which of its ports are yours is your own doc's frontmatter
  claim — so read it even when you drive nothing.
- `requirements.json` path (specification workdir) — the engineer's requirements, each with the
  stage that judges it. Read the rows that bear on your RTL: the ones judged by `rtl-design` are
  yours to satisfy by construction (a language rule, a hard-coded parameter, a structure the
  engineer pinned), and the bounds judged by `synthesis` and `power-analysis` decide pipeline
  depth, operator sharing, RAM vs. register file, and clock-gating granularity. Your `<child>.md`
  cites rows by id; the wording that binds you is in the row. A row that points at a file under
  `<intent>/` — a register map, a reference model — is read there.

## Prohibitions

- **Do not reverse-read your interface into existence.** Your ports come from the
  `top-io.json` / `interconnects.json` / `<child>.md §2` contract — never from an external
  verification harness (a reference top, `Makefile`, or `*_defines` from the verification
  environment) reverse-read until they line up. Your siblings were handed that same contract, and
  it is the only reason their RTL and yours meet.

## Output

Write your `rtl_modules[]` into one or more files of your choosing under `src/` (one file
may hold multiple modules). **STRICT Verilog-2001** — no SystemVerilog constructs
(`logic`/`always_ff`/`always_comb`/`typedef`/`enum`/`struct`/`interface`/`package`/…).
That is your discipline, per `references/coding-rules.md`; no gate decides it, and no
extension stands in for it. End the response with `STATUS: DONE` + a single JSON line, or
`STATUS: BLOCKED <reason>` (e.g. `<child>.md §2 Interface incomplete`).

```json
{
  "files":   ["src/<rel-path>"],
  "incdirs": ["src", "src/<rel-dir>"],
  "annotations": {
    "sgdc": { "sync_cell": ["<mod>"], "reset_synchronizer": ["<mod>"],
              "set_case_analysis": [{"port": "<port>", "value": 0}], "quasi_static": ["<sig>"] },
    "sdc":  { "create_generated_clock": [{"module": "<m>", "pin": "<p>"}],
              "set_multicycle_path": ["<desc>"], "set_false_path": ["<desc>"] }
  }
}
```

## Annotation rules (these feed lint-cdc + synthesis)

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
- `incdirs`: the include search paths your files `` `include `` through, relative to the stage
  root — `src` when your headers sit at the top of your tree, plus any subdirectory you include
  from. You **author your own file/include layout** (specification defines RTL modules, not file
  layout). Omit the field (or `[]`) only when your files use no `` `include `` — that is the
  genuine "no include dirs" case, not a guess. A child that uses includes but omits `incdirs` is a
  contract violation: every downstream filelist is generated from `rtl-files.json`, so a missing
  entry means a missing include path and the compile fails downstream — do not omit.
- **`files[]` is the compile order, not the set that leaves your run.** Everything you write under
  `src/` is delivered and versioned as one tree, listed or not. So list what the tool must compile,
  in the order it must see it; a macro header your files reach through `incdirs` needs no entry of
  its own.
