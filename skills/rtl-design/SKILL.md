---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, or recording each child's file layout and constraint annotations; not for verification, lint, or synthesis.
---

# RTL Design

Your sole responsibility: turn the boundary specification froze into authored RTL. You are a thin dispatcher — per-child sub-Tasks author every `.v` file, and a reviewer per child reads it back against its intent. You hold no RTL body, and every fix lands through a child re-dispatch.

**The split is yours.** Nothing upstream names the RTL modules: `design.md` §1.2 argues for a structure and the rows constrain it, but you are the first reader who has the RTL in front of them. Partition on the interface graph's edges, NOT by line counts: cut ONLY at clean elastic-handshake boundaries (`valid/ready` or `req/ack`); a skew- or phase-locked coupling is never a cut point — the modules it binds stay in one child, internalizing that coupling. Each child is thus one or more whole RTL modules forming a coupling cluster bounded by clean handshakes; a tightly-coupled fabric with no clean internal handshake is monolithic. Small leaf modules join their cluster — no line-count floor or size class. `<top_module>` is its own child and carries no logic. On a repair round the split already in `rtl-files.json` is the one to keep unless the repair is what changes it.

## Iron Rule

- **`design.md`, `requirements.json` and the boundary sidecars are the intent source.** Never modify them; no RTL-level adjustment overrides the boundary or a row.
## Artifacts

`<skill>` is this skill's own base directory, named on the first line of this file.

Read `{workdir}/dispatch.json` for this round's inputs: its `inputs` table maps each upstream key to a location, so `<key>/<subpath>` is how you address one. Every key resolves to the specification stage root, so `<design>` reaches its sibling sidecars too.

`caused_by` and `scope` name what this round is about, and they are independent: `scope` is what drifted under you, `caused_by` is the failing runs waiting on you (read each envelope). A round can carry both; answer both. `reasons` is a human's judgment on this repair. It outranks your own reading of the files. If you disagree, say so in `result.json` instead of acting against it.

| Path | What it is |
|---|---|
| `<manifest>/manifest.json` | `module` — the `<top_module>` name, and nothing else |
| `<design>/design.md` | The architecture it proposes, the boundary narrative, the joint obligations, the timing scenarios. Passed by path into the sub-Tasks |
| `<design>/top-io.json`, `clocks.json` | The boundary and the clocks. Passed by path into the sub-Tasks |
| `<requirements>/requirements.json` | The engineer's requirements, one row each with the stage that judges it. The child authors read whatever rows bear on their RTL, the numeric bounds synthesis and power-analysis will compare included; the intent reviewers hold the RTL to the rows judged by rtl-design. Passed by path into the sub-Tasks |
| `<intent>/` | The intent tree: the engineer's container — `brainstorm.md` plus whatever they delivered with it. Open a file here only when a requirements row points at it, and read it there rather than from any copy |

Everything below is produced under `{workdir}`. Each JSON sidecar's shape is `references/<name>.schema.json`.

| Path | What it is |
|---|---|
| `src/` | The authored RTL, the `<top_module>` file among it — delivered as one tree |
| `rtl-files.json` | Per-child `files[]` + `incdirs[]`. Its keys are this stage's child roster — nothing upstream carries one. Every downstream filelist is generated from it — no stage parses a text file list |
| `constraint-annotations.json` | Per-child SGDC/SDC annotations in real module names, read by lint-cdc and synthesis |
| `semantic-review/` | The intent reviews, written by their reviewers. Prose, not a verdict — delivered as one tree, so what you call the files in it is yours |
| `result.json` | The status envelope, written only by `finalize` |

## Task

Decide the split, then dispatch one Level-1 `Task(run_in_background=True)` per child, prompt per [`references/child-task-contract.md`](references/child-task-contract.md), handing each the paths that contract names, `<skill>` among them, plus the boundary ports and the cut edges you assigned it. Then send a brief status and end the turn. Their reports are what you write `rtl-files.json` and `constraint-annotations.json` from, keyed by child name.

Both sidecars must end up carrying an entry for every child you dispatched: every downstream filelist is generated from `rtl-files.json`, so a child missing from it never reaches a tool. A round that re-authored only some children therefore overlays its reports onto the entries already in `{workdir}` instead of writing the file from scratch. A child that reports `STATUS: BLOCKED` has no entry to write: close the round with `--fail-reason` naming it.

**The RTL does not ship until it compiles.** The full `rtl-files.json` file set compiles as one design before the round closes.

**The RTL does not ship until its intent has been reviewed.** Fresh Level-1 reviewers read the RTL this round ships against the design intent it came from, per [`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md).

Nothing reduces those reviews to a verdict. Read them and act: re-dispatch the children whose RTL is wrong, or close the round and name who must fix what you cannot. A review that finds a defect in `design.md` or a row is not yours to fix — that is the intent source.

**Write the envelope.**

```bash
python3 <skill>/scripts/rtl/__main__.py finalize --workdir {workdir} [--fail-reason "<one line>"] [--fix-owner <rule>]
```

`finalize` derives the envelope from disk. It validates both sidecars against their schemas, and refuses to write a pass while a file they name is not in `{workdir}`.

A failing envelope carries `fail_reason`. `finalize` derives it from the on-disk verdict, or takes your one line from `--fail-reason` when no on-disk state can express the failure.

`--fix-owner` names the rule that must act. A defect you could fix from here you already fixed by re-dispatching, so a failure is either the spec's (`specification`) or your own exhausted remedy. Naming yourself calls a human in. Omit it when you cannot tell.

Exit 0 means `result.json` was written, pass or fail. Exit 2 means it was not: the workdir is not in a state any verdict describes, and stderr says which part. Fix what it names and run it again — do not write the envelope yourself.

## Return Contract

Control returns to the caller, which decides what runs next from `result.json`.

Your sole completion signal is `{workdir}/result.json` present with `status=pass`; a missing one is incomplete, so re-enter idempotently.
