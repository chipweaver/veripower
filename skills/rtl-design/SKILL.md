---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, or recording each child's file layout and constraint annotations; not for verification, lint, or synthesis.
---

# RTL Design

Your sole responsibility: turn `manifest.json`'s child roster into authored RTL. You are a thin dispatcher. The per-child sub-Tasks author every `.v` file; deterministic scripts turn their reports into this stage's sidecars and envelope. You hold no RTL body, and every fix lands through a child re-dispatch.

## Iron Rule

- **`rtl-files.json` and `constraint-annotations.json` are `assemble`'s to write.** Never edit either directly.
- **`design.md` and the per-child `<child>.md` are the intent source.** Never modify either; no RTL-level adjustment overrides an architectural decision.

## Artifacts

Read `{workdir}/dispatch.json` for this round's inputs: its `inputs` table maps each upstream key to a location, so `<key>/<subpath>` is how you address one. Every key resolves to the specification stage root, so `<design>` reaches its sibling sidecars too.

`caused_by` and `scope` name what this round is about. `reasons` is a human's judgment on this repair. It outranks your own reading of the files. If you disagree, say so in `result.json` instead of acting against it.

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

## Actions

Dispatch one Level-1 `Task(run_in_background=True)` per child in `manifest.children[]`, prompt per [`references/child-task-contract.md`](references/child-task-contract.md). Then send a brief status and end the turn.

Finalize only once every dispatched child has reported. A child that never reports is caught by nothing: the exit gate reads the manifest, not the ledger, so it returns `pass` over a sidecar that is missing that child's RTL.

**Check the partition before you dispatch.**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py check-partition --manifest <manifest>/manifest.json --top <top_module>
```

Exit 1 means the manifest's top-integration child is bundled or miscovered. Run `finalize` and return.

**Build the sidecars once the children are in.** Dump each reaped child's `STATUS` + JSON to `{workdir}/reaped-children.json` first. The scripts read disk, not your reap context.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py assemble --workdir {workdir} --manifest <manifest>/manifest.json --top <top_module> [--seeded]
```

Pass `--seeded` on any round that has a prior baseline in `{workdir}`. Without it this round's `reaped-children.json` becomes the whole ledger, and every child you did not re-dispatch is dropped.

A build error exits non-zero with a message on stderr and no verdict on stdout. Pass that message to `finalize --fail-reason` and stop.

A verdict on stdout with exit 1 is a topology or blocked-child failure. Run `finalize`.

**Review the RTL against its intent.** One fresh Level-1 reviewer per child, per [`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md). You pass paths and read no RTL yourself. Run this on every finalize, not only a first delivery: a child re-authored on a later pass must be reviewed against the RTL it actually ships.

Aggregate the findings into `{workdir}/semantic-review.json`. A reviewer that returns nothing usable gets an `unavailable` finding, so a review that did not happen never reads as a review that found nothing.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py validate-review --review {workdir}/semantic-review.json
```

Exit 1 means the doc is unreadable or schema-invalid. Re-assemble it and re-run. That is yours to fix, not a re-dispatch.

Exit 0 prints the gate verdict. Act on its `loci`:

- empty (`gate=clear`) — go to `finalize`.
- `loci.rtl` — re-dispatch those children with their own findings as fix scope, then review again.
- `loci.spec` — no child's RTL can close a defect in the intent source. Go to `finalize` and name `specification`.

**Write the envelope.**

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py finalize --workdir {workdir} --module {module} --top <top_module> --manifest <manifest>/manifest.json [--fix-owner <rule>]
```

A failing envelope carries `fail_reason`. `finalize` derives it from the on-disk verdict, or takes your one line from `--fail-reason` when no on-disk state can express the failure.

`--fix-owner` names the rule that must act. A defect you could fix from here you already fixed by re-dispatching, so a failure is either the spec's (`specification`) or your own exhausted remedy. Naming yourself calls a human in. Omit it when you cannot tell.

Exit 0 means `result.json` was written, pass or fail. A non-zero exit is a program exception, including a `semantic-review.json` the schema rejects.

## Return Contract

Control returns to the caller, which decides what runs next from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is incomplete, so re-enter idempotently. `carry_self` never carries `semantic-review.json` forward on a repair, so a stale `clear` cannot survive to a later finalize.
