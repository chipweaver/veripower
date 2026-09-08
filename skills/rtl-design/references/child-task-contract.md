# Per-child RTL sub-Task contract

The rtl-design main thread decides the split and dispatches one Level-1 sub-Task per child
(including the top-integration child). Every child gets the identical contract below. Do not call the Task tool: a sub-Task of yours would append no event and sit outside the
kernel's accounting, where nothing could audit it.

## Inputs

The main thread hands over paths only; it reads none of these bodies.

- `<skill>` — this skill's base directory, and `<skill>/references/coding-rules.md`.
- Your child unit name, the RTL modules it covers, and the cut edges the main thread assigned it.
- `design.md`, `top-io.json`, `clocks.json`, `requirements.json` — the architecture it proposes,
  the boundary, the clocks, and the engineer's requirements. `design.md` is where the obligations
  more than one child must jointly keep are stated; you are held to those and may not restate them
  differently. **Every child reads `top-io.json`**, even one
  that drives no top-level port: which ports are yours is your own doc's frontmatter claim, and
  checking it against the boundary is how a wrong claim surfaces here rather than at the compile.
  Read the requirements rows that bear on your RTL — the ones judged by `rtl-design` are yours to
  satisfy by construction, and the bounds judged by `synthesis` / `power-analysis` decide pipeline
  depth, operator sharing, RAM vs. register file, and clock-gating granularity.

Field semantics live in each file's own schema under `specification/references/`.

## Prohibitions

- **Do not reverse-read your interface into existence.** Your ports come from the
  `top-io.json` / `design.md` boundary contract — never from an external
  verification harness (a reference top, `Makefile`, or `*_defines` from the verification
  environment) reverse-read until they line up. Your siblings were handed that same contract, and
  it is the only reason their RTL and yours meet.

## Output

Write your modules into one or more files of your choosing under `src/` (one file
may hold multiple modules). **STRICT Verilog-2001** — no SystemVerilog constructs
(`logic`/`always_ff`/`always_comb`/`typedef`/`enum`/`struct`/`interface`/`package`/…).
That is your discipline, per `references/coding-rules.md`; no gate decides it, and no
extension stands in for it. End the response with `STATUS: DONE` + a single JSON line, or
`STATUS: BLOCKED <reason>` (e.g. `top-io.json` names no port for an edge you were assigned).

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
  structures imply from the `top-io.json` / `clocks.json` contract you received. An omission is a
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
