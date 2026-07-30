---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, or recording each child's file layout and constraint annotations; not for verification, lint, or synthesis.
---

# RTL Design

Your sole responsibility: turn `manifest.json`'s child roster into authored RTL. You are a thin dispatcher — one fan-out wave of per-child sub-Tasks, a gating review wave, deterministic scripts in between. You hold no RTL body: every `.v` file is written and read only inside a sub-Task context, and every fix lands through a child re-dispatch.

## Iron Rule

- **`rtl-files.json` and `constraint-annotations.json` are `assemble`'s to write.** Never edit either directly.
- **`design.md` and the per-child `<child>.md` are the intent source.** Never modify either; no RTL-level adjustment overrides an architectural decision.
- **Minimal edit on any re-dispatch with prior valid RTL on disk.** Edit only the files this round's scope requires; every file outside it stays byte-identical. A needless rewrite re-fingerprints the artifact, which drops a human `pin` back to `proposed` — invisible from inside this stage, and the next signoff would sign text nobody reviewed.
- **Scripts are black boxes, never Read their source.** Invoke them per the command lines below (flags via `--help`); act on the documented failure protocol, not the source. Sole exception: debugging a suspected bug in a script itself.

## Artifacts

Read `{workdir}/dispatch.json` for this round's inputs: its `inputs` table maps each upstream key to a location, so `<key>/<subpath>` is how you address one. Every key resolves to the specification stage root, so `<design>` reaches its sibling sidecars too. The same file's `scope` / `caused_by` / `reasons` keys narrow this round.

| Path | What it is |
|---|---|
| `<manifest>/manifest.json` | The child roster: `module` (= `<top_module>`) + `children[]` (`name` / `doc` / `rtl_modules[]`). Drives the fan-out |
| `<children>/<child>.md × N` | Per-child sub-design — frontmatter + §2 Interface + §3 Internal Behavior are what each child derives its RTL from |
| `<design>/top-io.json`, `interconnects.json`, `clocks.json` | The boundary, the cut edges, the clocks. Passed by path into the sub-Tasks |
| `<design>/ppa.json` | PPA targets the micro-architecture must be bound to — a combinational divide that blows a timing target is a defect here, not at synthesis |

Everything below is produced under `{workdir}`. Each JSON sidecar's shape is `references/<name>.schema.json`.

| Path | What it is |
|---|---|
| `*.v` (`*.vh` headers) | The authored RTL, `<top_module>.v` among it. **STRICT Verilog-2001**: `rtl-files.schema.json` rejects a `.sv`/`.svh` extension because the kernel's `rtl` selectors match `*.v` alone; the content being V2001 is the child's discipline per `references/coding-rules.md` |
| `rtl-files.json` | Per-child `files[]` + `incdirs[]`. Every downstream filelist is generated from it — no stage parses a text file list |
| `constraint-annotations.json` | Per-child SGDC/SDC annotations in real module names, read by lint-cdc and synthesis |
| `semantic-review.json` | The gating per-child intent review — this stage's proposed oracle |
| `result.json` | The status envelope, written only by `finalize` |

## Workflow

Three machine contracts bracket this stage: what `dispatch.json` hands you, what the fan-out
sub-Tasks return, and what `finalize` hands back. The actions between them are yours to sequence.

### Entry contract

`dispatch.json`'s `inputs` table resolves the upstream locations (Artifacts above). Three
further keys narrow this round — with either narrowing key present, the scope is the union of both:

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
bundled or miscovered: run `finalize` and return without dispatching.

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
  `unavailable` marker is the only finding with no `fix_locus`).
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
Advisory findings (`over-engineering` at any severity, `minor`,
`unavailable`) never trip; they are recorded, with a `⚠ <child> <category>` line in the completion
summary.

**An rtl-locus trip you can fix in-stage, fix in-stage — self-converge.** Re-dispatch ONLY the
children named in `loci.rtl`, injecting each one's own semantic findings as fix scope
(dispatch-and-wait, the same primitive as the fan-out wave), then re-run the review wave; the
reviewer re-judges every round. `design.md` / `<child>.md` stay the immovable intent boundary, so a
fixer edits only its own child's RTL. Re-run `assemble` **WITH `--seeded`** every round — without
it this round's subset-only `reaped-children.json` becomes the whole ledger and every
already-passing child is dropped. A non-zero `assemble` (blocked-child or topology) stops the stage
and does not fall through to the review wave. There is no round cap.

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

## Return Contract

Control returns to the caller, which decides what runs next from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is incomplete, so re-enter idempotently. `carry_self` never carries `semantic-review.json` forward on a repair, so a stale `clear` cannot survive to a later finalize.
