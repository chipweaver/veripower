---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, or recording each child's file layout and constraint annotations; not for verification, lint, or synthesis.
---

# RTL Design

Your sole responsibility: orchestrate per-child RTL authoring as a pure dispatcher over `manifest.json`'s child roster: the per-child sub-Tasks author the RTL; deterministic finalize scripts then produce `rtl-files.json` (per-child file layout), `constraint-annotations.json` (per-child SGDC/SDC annotations), and `result.json` from their reaped reports. You never author or read RTL yourself.

**Load mode:** this skill runs main-thread, invoked via `Skill(veripower:rtl-design)` by its caller (not dispatched as a Task subagent). It uses the Task tool for one fan-out wave (one Level-1 sub-Task per child unit, including the top-integration child); finalize is then deterministic main-thread scripts, not a sub-Task. You never author RTL inline.

## Iron Rule

- Every RTL file on disk MUST appear in `rtl-files.json`; `assemble` writes it and the two sidecars from the reaped reports, and you never edit either file directly.
- **No child RTL in the main thread:** every child (including the top-integration child) is dispatched in the fan-out wave. You consume each sub-Task's `files[]` paths only and **MUST NOT read the dispatched child's** `.v`/`.sv` content back into your context. There is no inline TOP authoring: even a single child is written by a sub-Task, and every fix lands through a child re-dispatch, never a main-thread edit.
- **`design.md` and the per-child `<child>.md §1–§5` are an immovable boundary.** You never modify either, and no RTL-level adjustment overrides an architectural decision. If a fix would need one of them, stop this round with `status=fail`.
- **Minimal edit on any re-dispatch with prior valid RTL on disk.** Edit only the files this round's scope requires (the entry contract determines it); every file outside that scope MUST stay byte-identical to the prior run. Modifying anything outside it is prohibited.
- **Never silently sacrifice one acceptance target for another.** The PPA targets in `<design>/ppa.json` and the cycle budget in `design.md` can pull against each other: making a combinational divide iterative buys timing and spends latency. When you cannot satisfy both, report the numbers you actually achieved plus the trade-off in `result.json`, and let the caller decide. Quietly meeting one target by breaking another — timing, latency, or bit-exactness — is the failure mode this rule exists to stop.
- **`<child>.md §2 Interface` incomplete:** if the interface spec is missing or underspecified, the stage fails with `fail_reason="<child>.md §2 Interface incomplete"`; do not invent interfaces.
- **Scripts are black boxes, never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr, stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |

### External reference inputs

Read `{workdir}/dispatch.json`: its `inputs` table maps each read-only upstream input to its location, so `<key>` below denotes that location and you read `<key>/<subpath>`. Every key resolves to the specification stage root, so `<design>` reaches its sibling JSON sidecars too. The same file's `scope` / `caused_by` / `reasons` keys are what narrow this round (see the entry contract).

| Path | Schema / Format | Use |
|---|---|---|
| `<design>/top-io.json` + `<design>/interconnects.json` | `specification/references/{top-io,interconnects}.schema.json` | The boundary and the cut edges. Passed by path to the child sub-Tasks (`references/child-task-contract.md`); the main thread does not read them. |
| `<design>/clocks.json` | `specification/references/clocks.schema.json` | Clock definitions. Passed by path to the child sub-Tasks — a `"generated": true` entry is the `create_generated_clock` the child must report; the main thread does not read it. |
| `<manifest>/manifest.json` | JSON (`{module, children:[{name, doc, rtl_modules, brainstorm_anchor}]}`) | Child roster — drives the fan-out `N = len(children[])` (every child, incl. the top-integration child). |
| `<children>/<child>.md` × N | Custom markdown (frontmatter + §1–§5) | Per-child sub-design: frontmatter (`ports` / `clocks` / `features`) + §2 Interface / §3 Internal Behavior drive per-child RTL derivation. |
| `<design>/ppa.json` | `specification/references/ppa.schema.json` | The PPA targets this RTL must hit. Read each entry's `dim` and numeric `target` yourself, and bind the micro-architecture to them (a combinational divide that blows a timing target is a defect here, not at synthesis). |

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `<top_module>.v` | Verilog-2001 | Top integration RTL — authored by the top-integration child sub-Task, never the main thread. |
| `*.v` (per child; `*.vh` headers) | Verilog-2001 | Each child writes its `rtl_modules[]` into `.v` files of its own choosing (spec defines modules, not layout); the child's returned `files[]` is authoritative. **STRICT Verilog-2001** — `references/rtl-files.schema.json` rejects a `.sv`/`.svh` extension, because the kernel's downstream `rtl` selectors match `*.v` alone (a `.sv` artifact silently drops out of the dependency graph). The content being V2001 is the child's discipline per `references/coding-rules.md`; no gate decides it. |
| `rtl-files.json` | `references/rtl-files.schema.json` | Per-child `files[]` + `incdirs[]` — written by `assemble` from the reaped reports. Every downstream filelist is generated from it (simulation, synthesis, lint-cdc); no stage parses a text file list. |
| `constraint-annotations.json` | `references/constraint-annotations.schema.json` | Per-child SGDC + SDC annotations in the child's real module names — written by `assemble`; read by the lint-cdc and synthesis agents. |
| `semantic-review.json` | `references/semantic-review.schema.json` | Gating per-child intent review, aggregated by the main thread on every clean-gate finalize. |

## Workflow

Three machine contracts bracket this stage: what `dispatch.json` hands you, what the fan-out
sub-Tasks return, and what `finalize` hands back. Between them the actions are yours to
sequence — each names what it reads and writes, and every script fails loud on a missing
input, so none of this is an execution order to be walked.

### Entry contract

Read `{workdir}/dispatch.json`. Its `inputs` table maps each read-only upstream input to its
location, so `<key>` denotes that location and you read `<key>/<subpath>`; every key resolves to
the specification stage root, so `<design>` reaches its sibling JSON sidecars too.

Three keys narrow this round — when either narrowing key is present, the scope is the union of both:

- `caused_by` — the `result.json` of each upstream failure this round answers. Read each, and its
  sibling `reports/` or `reports_*/` when the failure is a PPA miss, since a bottleneck is located
  in the raw report and not in the envelope. A pointer, not a boundary: if what you read puts the
  defect elsewhere, widen and record why in `result.json`.
- `scope` — module-relative paths, or `<file>:<line>` anchors, that this round should touch.
- `reasons` — a human's judgment on this repair. It outranks your own reading of the files; if you
  disagree, say so in `result.json` rather than acting against it.

With neither narrowing key: prior RTL already in `{workdir}` makes this a re-verify — re-author no
child, re-run the gate on the RTL that is there, every file byte-identical. An empty `{workdir}`
means all children.

`manifest.json` is the child roster SSoT: `.module` = `<top_module>`, and `children[]` carries each
child's `name` / `doc` / `rtl_modules[]`.

### Fan-out contract

One Level-1 `Task(run_in_background=True)` per child in the to-dispatch set, prompt per
[`references/child-task-contract.md`](references/child-task-contract.md). Every child including the
top-integration child — no `name=="top"` special-casing, no N==1 inline exemption. **No Level-2
dispatch:** none of them dispatches a sub-Task of its own.

Dispatch, send a brief status, and end the turn. On wake-up, reap each child's harness `STATUS:`
last line plus its JSON line (`{files, incdirs?, annotations}`), or `STATUS: BLOCKED <reason>`.
Never finalize against a partial report set. A `BLOCKED` child is `status=fail` + `fail_reason`;
its re-dispatch waits for a repair round.

### Actions

**Before dispatching, check the partition.**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py check-partition --manifest <manifest>/manifest.json --top <top_module>
```

Exit code is the truth (0 ok / 1 fail). Non-zero means the manifest's top-integration child is
bundled or miscovered: run `finalize`, which surfaces that `fail_reason` into a `status=fail`
`result.json`, then return without paying for a doomed fan-out.

**Once every dispatched child has reported, land the reports and build the sidecars.** Dump each
reaped child's `STATUS` + JSON to `{workdir}/reaped-children.json` — the scripts read disk, not
your reap context (`STATUS: DONE`+JSON → `{"status":"done",...}`; `STATUS: BLOCKED <r>` →
`{"status":"blocked","reason":"<r>"}`; a straight copy, no judgment). Then:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py assemble --workdir {workdir} --manifest <manifest>/manifest.json --top <top_module> [--seeded]
```

`assemble` writes both sidecars and runs the post exit-gate in one step. A **build error**
(malformed reports or sidecars, or a file whose extension `references/rtl-files.schema.json`
rejects — RTL is `.v`/`.vh`, never `.sv`) exits non-zero with a stderr message and **no stdout
verdict**: pass that message to `finalize --fail-reason` and stop. Otherwise it prints the
exit-gate verdict JSON on stdout, exit code = truth (topology + blocked-child); a fail verdict
stops the stage and `finalize` writes it into `result.json`. Pass `--seeded` whenever a prior
baseline is already in `{workdir}`, never on a first delivery's initial build.

**RTL on disk needs an intent self-check before it ships.** One fresh Level-1
`Task(run_in_background=True)` per `manifest.children[]`, per
[`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md) — you hand over
paths only (the child's `files[]`, its per-child doc via `manifest.children[].doc`, the `design.md`
§1.4 slice) and read no RTL yourself. This runs on every finalize, not only a first delivery: a
child re-authored on a later pass must be reviewed against the RTL it actually ships. Aggregate
into `{workdir}/semantic-review.json` (schema
[`references/semantic-review.schema.json`](references/semantic-review.schema.json)):

- `STATUS: DONE` + valid finding JSON → fold its findings in (each carries a reviewer-assigned
  `fix_locus ∈ {rtl, spec}`).
- `STATUS: BLOCKED`, or malformed/unparseable JSON → record a `{child, severity:"minor",
  category:"unavailable", location:"-", summary:"review unavailable: <reason>"}` finding (the
  `unavailable` marker is the only finding with no `fix_locus`). Never silently treated as ok, but
  a DISTINCT category from substantive concerns.
- The whole wave unusable (nothing assemblable at all, e.g. total dispatch failure) → do NOT gate:
  write the minimal doc with one `unavailable` finding, note it in the completion summary, carry on.

Then reduce it — the verdict is script-owned, never judged by eye:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py validate-review --review {workdir}/semantic-review.json
```

A non-zero exit means the doc is unreadable or schema-invalid: re-assemble it and re-run (a
main-thread fix, NOT a re-dispatch). On exit 0 it prints
`{"gate":"trip"|"clear","flagged":[{child,category,severity,fix_locus}…],"loci":{"rtl":[…],"spec":[…]},"spec_confidence":"high"|"medium"|"low"|null}`
— the mechanical `category × severity` reduction partitioned by `fix_locus`, the same one
`finalize` re-computes in-process and writes verbatim as `stage_specific.semantic_gate`.
`spec_confidence` is the **minimum** `confidence` over every `fix_locus=spec` finding, not just the
gating subset (reviewer-reported, defaulting to `low` when omitted; `null` when there is no
spec-locus finding at all). Advisory findings (`over-engineering` at any severity, `minor`,
`unavailable`) never trip; they are recorded, with a `⚠ <child> <category>` line in the completion
summary.

**An rtl-locus trip you can fix in-stage, fix in-stage — self-converge.** Re-dispatch ONLY the
children named in `loci.rtl`, injecting each one's own semantic findings as fix scope
(dispatch-and-wait, the same primitive as the fan-out wave), then re-run the review wave; the
reviewer re-judges every round. `design.md` / `<child>.md` stay the immovable intent boundary, so a
fixer edits only its own child's RTL. Re-run `assemble` **WITH `--seeded`** every round — without
it this round's subset-only `reaped-children.json` becomes the whole ledger and every
already-passing child is dropped. A non-zero `assemble` (blocked-child or topology) stops the stage
and does not fall through to the review wave. There is no round cap, and the loop is intra-stage
scratch: the stage produces one result at exit. Files a re-dispatched child superseded stay in the
run's scratch workdir, never in the sidecars, so they are never promoted.

**A spec-locus trip you cannot fix from RTL — fail-out.** `loci.spec` non-empty means the defect is
in the intent source, so no child's RTL can close it: go straight to `finalize`, which folds the
trip into `status=fail` with a spec-rooted `fail_reason` and carries
`semantic_gate.{loci.spec, spec_confidence}` for the kernel's upstream route. With both loci
non-empty, self-converge the rtl-locus children first; whatever `loci.spec` survives then fails
out. You MUST NOT override a `gate=trip` to pass.

**Finally, write the envelope.**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py finalize --workdir {workdir} --module {module} --top <top_module> --manifest <manifest>/manifest.json [--fix-owner <rule>]
```

**Naming the fix owner.** On a failure, add `--fix-owner <rule>`. A defect you can fix from here you
already fixed, by re-dispatching the child; so a failure means either the semantic gate found the
defect in the spec (`--fix-owner specification`, and the gate's `loci`/`spec_confidence` stay in the
envelope as the account behind it) or the remedy is exhausted and it is yours (name yourself, which
calls a human in). Omit it when you read the child reports and still cannot tell.

`finalize` re-derives the exit verdict in-process over the converged sidecars (`status` +
`fail_reason` + `artifacts[]`, verbatim), schema-validates `semantic-review.json`, and folds its
gate verdict in as `stage_specific.semantic_gate`. The free-text run narration is NOT in
`result.json` — it belongs in `events.jsonl`. Exit 0 = written (status pass or fail); a non-zero
exit is a program exception (BLOCKED), including a `semantic-review.json` the schema rejects.

`--fail-reason "<one line>"` is the early-exit form, for a failure no on-disk state can express (a
build error): it writes the `status=fail` envelope with that reason instead of re-deriving a
verdict, and still enumerates whatever the sidecars hold. Never hand-write `result.json` yourself;
an envelope that violates the schema is reaped as blocked rather than as a routable fail.

In the completion summary, emit one line `semantic-gate: <clear | trip | unavailable>; see
semantic-review.json`. If any finding is `severity=critical` (possible on a cleared gate, when the
critical finding is in a non-gating category such as `over-engineering`), add `⚠ <child> critical
<category> finding — recommend operator review before downstream`.

## Completion Gate

- [ ] **Mechanical gate:** the `assemble` exit gate exited 0; `{workdir}/rtl-files.json` and `{workdir}/constraint-annotations.json` were written by `assemble`.
- [ ] **Semantic gate:** the review wave ran on this round's RTL, `semantic-review.json` was written and validated, and its verdict was applied by locus; a `gate=trip` was never overridden to pass.
- [ ] **Finalize:** `finalize` wrote `{workdir}/result.json`, which owns `status` / `fail_reason` / `artifacts[]` / `semantic_gate` (the framework schema-validates it at stage completion; this gate does not re-run that check).
- [ ] No Iron Rule was triggered.

## Return Contract

Main-thread skill: control returns directly to the caller, which decides what runs next from `{workdir}/result.json` (`status ∈ {pass, fail}`). There is no Task-subagent `STATUS:` last-line signal from this skill itself, and no human review loop.

Each dispatched per-child sub-Task ends with a harness-level `STATUS: DONE` + a `{"files": [...], "incdirs"?: [...], "annotations": {...}}` JSON line, or `STATUS: BLOCKED <reason>` (schema in `references/child-task-contract.md`). You consume those signals, not the caller.

Your sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`; a missing `result.json` is incomplete, so re-enter idempotently. `carry_self` never carries `semantic-review.json` forward on a repair, and every re-entry re-runs the semantic gate on the current RTL, so a stale `clear` cannot survive to finalize.

## Bundled References

- [`references/child-task-contract.md`](references/child-task-contract.md) — the per-child sub-Task prompt + returned annotation schema (dispatched in the fan-out wave).
- [`references/coding-rules.md`](references/coding-rules.md) — RTL coding rules (naming / ports / clocks / resets / FSM / RAM / low-power / datapath).
- [`references/constraint-annotations.schema.json`](references/constraint-annotations.schema.json) — schema for `constraint-annotations.json`, the per-child SGDC/SDC annotations.
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/rtl-files.schema.json`](references/rtl-files.schema.json) — schema for `rtl-files.json`, the per-child file layout every downstream filelist is generated from.
- [`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md) — per-child semantic review sub-Task contract (gating; dispatched once RTL is on disk).
- [`references/semantic-review.schema.json`](references/semantic-review.schema.json) — schema for the aggregated `semantic-review.json`.
- [`${CLAUDE_PLUGIN_ROOT}/framework/references/schemas/envelope.schema.json`](../../framework/references/schemas/envelope.schema.json) — common envelope schema.
