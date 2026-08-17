---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, or recording each child's file layout and constraint annotations; not for verification, lint, or synthesis.
---

# RTL Design

Your sole responsibility: turn `manifest.json`'s child roster into authored RTL. You are a thin dispatcher — the per-child sub-Tasks author every `.v` file, and a reviewer per child reads it back against its intent. You hold no RTL body, and every fix lands through a child re-dispatch.

## Iron Rule

- **`design.md` and the per-child `<child>.md` are the intent source.** Never modify either; no RTL-level adjustment overrides an architectural decision.
## Artifacts

`<skill>` is this skill's own base directory, named on the first line of this file.

Read `{workdir}/dispatch.json` for this round's inputs: its `inputs` table maps each upstream key to a location, so `<key>/<subpath>` is how you address one. Every key resolves to the specification stage root, so `<design>` reaches its sibling sidecars too.

`caused_by` and `scope` name what this round is about, and they are independent: `scope` is what drifted under you, `caused_by` is the failing runs waiting on you (read each envelope). A round can carry both; answer both. `reasons` is a human's judgment on this repair. It outranks your own reading of the files. If you disagree, say so in `result.json` instead of acting against it.

| Path | What it is |
|---|---|
| `<manifest>/manifest.json` | The child roster: `module` (= `<top_module>`) + `children[]` (`name` / `doc` / `rtl_modules[]`). Drives the fan-out |
| `<children>/<child>.md × N` | Per-child sub-design — frontmatter + §2 Interface + §3 Internal Behavior are what each child derives its RTL from |
| `<design>/top-io.json`, `interconnects.json`, `clocks.json` | The boundary, the cut edges, the clocks. Passed by path into the sub-Tasks |
| `<design>/ppa.json` | The area / timing-slack / power targets this RTL is judged against. Passed by path into the sub-Tasks |

Everything below is produced under `{workdir}`. Each JSON sidecar's shape is `references/<name>.schema.json`.

| Path | What it is |
|---|---|
| `*.v` (`*.vh` headers) | The authored RTL, `<top_module>.v` among it |
| `rtl-files.json` | Per-child `files[]` + `incdirs[]`, keys in manifest order. Every downstream filelist is generated from it — no stage parses a text file list |
| `constraint-annotations.json` | Per-child SGDC/SDC annotations in real module names, read by lint-cdc and synthesis |
| `semantic-review/*.md` | The intent reviews, written by their reviewers. Prose, not a verdict |
| `result.json` | The status envelope, written only by `finalize` |

## Task

Dispatch one Level-1 `Task(run_in_background=True)` per child in `manifest.children[]`, prompt per [`references/child-task-contract.md`](references/child-task-contract.md), handing each the paths that contract names, `<skill>` among them. Then send a brief status and end the turn. Their reports are what you write `rtl-files.json` and `constraint-annotations.json` from, keyed by child name.

Both sidecars must end up carrying an entry for every child in the manifest: every downstream filelist is generated from `rtl-files.json`, so a child missing from it never reaches a tool. A round that re-authored only some children therefore overlays its reports onto the entries already in `{workdir}` instead of writing the file from scratch, and `finalize` stops the round while an entry is missing. A child that reports `STATUS: BLOCKED` has no entry to write: close the round with `--fail-reason` naming it.

**The RTL does not ship until it compiles.** The full `rtl-files.json` file set compiles as one design before the round closes.

**The RTL does not ship until its intent has been reviewed.** Fresh Level-1 reviewers read the RTL this round ships against the design intent it came from, per [`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md).

Nothing reduces those reviews to a verdict. Read them and act: re-dispatch the children whose RTL is wrong, or close the round and name who must fix what you cannot. A review that finds a defect in `design.md` or a `<child>.md` is not yours to fix — that is the intent source.

**Write the envelope.**

```bash
python3 <skill>/scripts/rtl/__main__.py finalize --workdir {workdir} --manifest <manifest>/manifest.json [--fail-reason "<one line>"] [--fix-owner <rule>]
```

`finalize` derives the envelope from disk. It validates both sidecars against their schemas, and refuses to write a pass while a manifest child has no entry in them or a file they name is not in `{workdir}`.

A failing envelope carries `fail_reason`. `finalize` derives it from the on-disk verdict, or takes your one line from `--fail-reason` when no on-disk state can express the failure.

`--fix-owner` names the rule that must act. A defect you could fix from here you already fixed by re-dispatching, so a failure is either the spec's (`specification`) or your own exhausted remedy. Naming yourself calls a human in. Omit it when you cannot tell.

Exit 0 means `result.json` was written, pass or fail. Exit 2 means it was not: the workdir is not in a state any verdict describes, and stderr says which part. Fix what it names and run it again — do not write the envelope yourself.

## Return Contract

Control returns to the caller, which decides what runs next from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is incomplete, so re-enter idempotently.
