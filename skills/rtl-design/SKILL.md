---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, or recording each child's file layout and constraint annotations; not for verification, lint, or synthesis.
---

# RTL Design

Your sole responsibility: orchestrate per-child RTL authoring as a pure dispatcher over `manifest.json`'s child roster: the per-child sub-Tasks author the RTL; deterministic finalize scripts then produce `rtl-files.json` (per-child file layout), `constraint-annotations.json` (per-child SGDC/SDC annotations), and `result.json` from their reaped reports. You never author or read RTL yourself.

**Load mode:** this skill runs main-thread, invoked via `Skill(veripower:rtl-design)` by its caller (not dispatched as a Task subagent). It uses the Task tool for one fan-out wave (one Level-1 sub-Task per child unit, including the top-integration child); finalize is then deterministic main-thread scripts, not a sub-Task. You never author RTL inline.

## When to Use

- Write new RTL for a module.
- Modify existing RTL (bug fix, PPA tuning, or architecture change).
- Maintain the RTL directory structure.
- Record each child's SDC / SGDC constraint annotations.

## Iron Rule

- Every RTL file on disk MUST appear in `rtl-files.json` (contract violation — a missing entry hides source files from consumers, whose filelists are generated from it).
- **No child RTL in the main thread:** every child (including the top-integration child) is dispatched in the fan-out wave. You consume each sub-Task's `files[]` paths only (the scripts aggregate them into `rtl-files.json`) and **MUST NOT read the dispatched child's** `.v`/`.sv` content back into your context — child RTL would otherwise compound across the long-lived main thread. There is no inline TOP authoring: even a single child is written by a sub-Task.
- **No whole-design elaboration in any child sub-Task:** child sub-Tasks obey the elaboration / anti-reverse-read prohibitions in `references/child-task-contract.md` (a unit child may best-effort self-lint its own module only); integration/elaboration correctness is verified by downstream verification.
- **`<child>.md §2 Interface` incomplete:** if the interface spec is missing or underspecified, write `status=fail` + `fail_reason="<child>.md §2 Interface incomplete"`; do not invent interfaces.
- **Minimal edit on any re-dispatch with prior valid RTL on disk.** Edit only the files this round's task actually requires (scope is determined in Step 1); every file outside that scope MUST stay byte-identical to the prior run — a full rewrite on a narrow fix defeats the incremental kernel's per-file cascade.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{failing_result}` | Optional. The failed stage's canonical `result.json` path (`stage_specific` shape per that stage's schema); when present, its `stage_specific.violations[]` supplies this round's fix scope (Step 1). |
| `{directive_path}` | Optional. Fix-scope hint file; Read it first — priority over the trigger content and the incremental diff. |

### External reference inputs

Each read-only upstream input's location is injected — read `inputs.json` in your `{workdir}`; below, `<key>` denotes that input's location, so you read `<key>/<subpath>` (`design`/`manifest`/`children` all resolve to the specification stage root).

| Path | Schema / Format | Use |
|---|---|---|
| `<design>/top-io.json` + `<design>/interconnects.json` | `specification/references/{top-io,interconnects}.schema.json` | The boundary and the cut edges. Passed by path to the child sub-Tasks (`references/child-task-contract.md`); the main thread does not read them. |
| `<design>/clocks.json` | `specification/references/clocks.schema.json` | Clock definitions. Passed by path to the child sub-Tasks — a `"generated": true` entry is the `create_generated_clock` the child must report; the main thread does not read it. |
| `<manifest>/manifest.json` | JSON (`{module, children:[{name, doc, rtl_modules, brainstorm_anchor, role}]}`) | Child roster — drives the fan-out `N = len(children[])` (every child, incl. the top-integration child). |
| `<children>/<child>.md` × N | Custom markdown (frontmatter + §1–§5) | Per-child sub-design: frontmatter (`ports` / `clocks` / `features` / `file_path`) + §2 Interface / §3 Internal Behavior drive per-child RTL derivation. |

When `{failing_result}` is injected, read additional context from the same directory as the trigger file: when the trigger carries `violations[]` / `ppa_actual[]`, they are the primary inputs (a trigger without them — e.g. coverage-rooted — falls back to Step 2's module-wide mapping). When a PPA dimension is present (`ppa_actual` non-empty), also read the sibling `reports/` or `reports_*/` subdirectory (`timing_*.rpt` / `area.rpt` / `power_*.rpt`) to locate the bottleneck down to the RTL module. The specific read scope is driven by the trigger's content; do not enumerate it ahead of time.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `<top_module>.v` | Verilog-2001 | Top integration RTL — authored by the top-integration child sub-Task, never the main thread. |
| `*.v` (per child; `*.vh` headers) | Verilog-2001 | Each child writes its `rtl_modules[]` into `.v` files of its own choosing (spec defines modules, not layout); the child's returned `files[]` is authoritative. **STRICT Verilog-2001** — a `.sv` extension or any SystemVerilog-only construct (`logic`/`always_ff`/`typedef`/…) is rejected by `check-conformance`'s dialect gate, because the kernel's downstream `rtl` selectors match `*.v` alone (a `.sv` artifact silently drops out of the dependency graph). |
| `rtl-files.json` | `references/rtl-files.schema.json` | Per-child `files[]` + `incdirs[]` — written by `assemble` from the reaped reports. Every downstream filelist is generated from it (simulation, synthesis, lint-cdc); no stage parses a text file list. |
| `constraint-annotations.json` | `references/constraint-annotations.schema.json` | Per-child SGDC + SDC annotations in the child's real module names — written by `assemble`; read by the lint-cdc and synthesis agents. |
| `semantic-review.json` | `references/semantic-review.schema.json` | Gating per-child intent review (Step 4.4), aggregated by the main thread on every clean-gate finalize. |

## Workflow (pure-orchestrator; one fan-out wave + scripted finalize)

### Fan-out Dispatch Contract

- **No Level 2 dispatch:** dispatch only Level-1 per-child sub-Tasks; none dispatches a sub-Task of its own.
- **Dispatch-and-wait:** after dispatching, send a brief status and end the turn. Reap each, and finalize only after all dispatched children have reported — never against a partial set.
- **Sub-Task `STATUS: BLOCKED`:** if a dispatched child comes back blocked (no usable result — a crash, not a `fail` verdict), map it to `status=fail` + `fail_reason` and defer re-dispatch to a repair round.

### Step 1: Read inputs, determine scope

Read `manifest.json` (`.module` =
`<top_module>`; the `children[]` dispatch roster: `name` + `doc` + `rtl_modules[]`). Nothing else is
read up front — no `design.md`, no `<child>.md` body, no RTL, and no upstream `result.json`;
the per-child sub-Tasks read their own docs. (Step-1 source 3 below consults `{workdir}/changed-inputs.md`
for scope when present.)

The framework has already carried your previous round's RTL and the two sidecars
into the workdir — edit them in place. Read the
specification from the `design`/`manifest`/`children` locations named in `inputs.json`.

Determine this round's edit scope from the first available source:
1. `{directive_path}`'s `fix_locus` when injected — Read that sibling file first; authoritative.
2. Else, on a `{failing_result}`, its `stage_specific.violations[]` (+ `ppa_actual[]` if present) —
   modify only the listed files; modifying anything outside is prohibited (see Red Flags). If the
   trigger is unreadable, write `result.json` with `status=fail` +
   `stage_specific.fail_reason="failing_result not readable"` and exit. When `ppa_actual` is
   non-empty, also read the trigger's sibling `reports/` or `reports_*/` subdirectory to locate the
   bottleneck RTL module.
3. Else, if `{workdir}/changed-inputs.md` is present, it lists the input files that changed since
   this stage's last run — map each to affected children (a `<child>.md` → that child; `design.md`
   → module-wide). If it is absent or empty but the framework's carry brought forward a prior
   canonical (a re-verify, not a first delivery), re-author no child: re-run Step 4's gate on the
   carried RTL and finalize; every file stays byte-identical.
4. Else (a first delivery, no prior canonical) ALL children.

Map the scope to affected children per Step 2. The module-level `design.md` + per-child `<child>.md`
set are an immovable boundary, never modified — if a fix would need either, stop this round (see Red
Flags).

**Pre-dispatch check (fail-fast).** After reading `manifest.json` and before the Step 3
fan-out, run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py check-partition --manifest <manifest> --top <top_module>
```

Its exit code is the truth (0 ok / 1 fail). On a non-zero exit, run `finalize` (Step 4.5) — it surfaces
the coverage `fail_reason` directly into a `status=fail` `result.json` — and return without dispatching, so
a bundled or miscovered top-integration child never pays authoring cost. (This is the same coverage/purity
check the Step 4.2 exit gate re-runs; the pre-dispatch run only spares a doomed fan-out.)

### Step 2: map_to_child (when scope is narrower than all children)

(Applies whenever Step 1 narrowed the scope — a directive, a `{failing_result}`, or a `changed-inputs.md` change-set. On
a first delivery the scope is ALL children and this step is skipped.)

1. Read `manifest.json` and the frontmatter of each `<child>.md` listed under
   `manifest.children[].doc` (Grep `^---` block only — ~15 lines per child). This frontmatter read is
   the only extra read scope-mapping adds — not RTL, not `design.md`.
2. For each `violations[]` entry, map to `affected_children[]` via the most specific available key:
   - `frontmatter.file_path` matches the trigger's `file` field → that child;
   - `frontmatter.features[]` contains a feature mentioned in the violation message → that child;
   - else fall back to "module-wide" (mark all children as affected).
3. Dispatch behaviour:
   - If `affected_children[]` is a strict subset and the top-integration interconnect is unaffected:
     re-dispatch only those children (a reduced fan-out wave).
   - Else (module-wide, or a TOP-level interconnect violation): re-dispatch ALL affected children
     including the top-integration child (if the interconnect changed).

### Step 3: Fan-out wave

Dispatch the to-dispatch set as `Task(run_in_background=True)`, one sub-Task per child — **all
`len(manifest.children[])` children on a first delivery (scope=ALL); the affected subset when scope is narrowed**. Every
child (including the top-integration child) is dispatched here — no `name=="top"` special-casing, no
N==1 inline exemption (even a single child is one sub-Task). The per-child sub-Task prompt + the
returned annotation schema are in [`references/child-task-contract.md`](references/child-task-contract.md).

After dispatching, end the turn.
On wake-up, reap each dispatched child's harness `STATUS:` last line + its JSON line. Proceed to
Step 4 only after every dispatched child has reported (DONE or BLOCKED); if woken with fewer reports
than dispatched, keep waiting (do not finalize against a partial report set).

### Step 4: Finalize (scripts + gates + semantic gate) + result.json

**4.1 Serialize reaped reports → `{workdir}/reaped-children.json`** — your single transcription act: the
finalize scripts read only disk, not your reap context, so dump each reaped child's `STATUS` + JSON to this
one file for them (`STATUS: DONE`+JSON → `{"status":"done",...}`; `STATUS: BLOCKED <r>` →
`{"status":"blocked","reason":"<r>"}`). A straight copy, no judgment.

**4.2 Build + exit gate** (`<manifest>` = `<manifest>/manifest.json`; `<top_module>` =
`manifest.module`; `<design>` = `<design>/design.md`):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py assemble --workdir {workdir} --manifest <manifest> --top <top_module> [--seeded]
```

`assemble` writes the two sidecars and runs the post exit-gate in one step. A **build error**
(malformed reports or sidecars) yields a non-zero exit with a stderr message and **no stdout verdict** (distinct
from a gate-fail verdict); hand-write `{workdir}/result.json` as a `status=fail` envelope with the stderr as
`fail_reason`, and stop. Otherwise it prints the exit-gate verdict JSON on stdout; exit code = truth
(topology + blocked-child); a fail verdict stops the stage — Step 4.5's `finalize` writes it into
`result.json`. (`--seeded` whenever the framework's carry brought forward a prior baseline — canonical existed — never on a first delivery's initial build.)

**4.3 Conformance gate + self-converge loop** (deterministic; runs EVERY invocation):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py check-conformance --workdir {workdir} --manifest <manifest> --top <top_module> --interconnects <design>/interconnects.json
```

On exit 0, go to 4.4. Exit 1 = spec↔RTL presence **or Verilog-2001 dialect** violations (each names a
`child`; `top_instantiation` also carries `owner_child`; a `dialect` violation names the offending `file`
plus its `sv_construct` or `.sv`/`.svh` extension). These are child-authoring defects (fix-locus = the
child), so self-converge:

- Re-dispatch set = `{v.child} ∪ {v.owner_child}` over all violations — the `owner_child` union lets a
  `top_instantiation` violation reach the sibling that renamed the module, not only the top child. You
  read the **verdict only — never the RTL**.
- Re-dispatch ONLY those children (reduced fan-out, `references/child-task-contract.md`), injecting the
  conformance verdict slice as fix-scope feedback (dispatch-and-wait per round, the same primitive as the
  fan-out wave). **manifest name is authoritative**: a child MUST author its
  `manifest.children[].rtl_modules[]` name verbatim (renaming is itself a violation `check #1` catches).
- Re-run `assemble` **WITH `--seeded`** (CRITICAL — without it the round's subset-only
  `reaped-children.json` evicts every already-passing child via `merge_filter`'s roster∩fresh), then
  `check-conformance`. `assemble`'s verdict is authoritative every round exactly as in 4.2 — a non-zero
  `assemble` (blocked-child or topology) stops the stage with `status=fail` and does not fall through to
  `check-conformance`; otherwise loop until `check-conformance` passes. The loop is intra-stage scratch —
  the stage produces one result at exit, the re-dispatches are not externally visible, and no persistent
  "pending finalize" state carries across.
- On convergence, rebuild a full-roster `reaped-children.json` (all children `status=done`,
  reconstructing each already-passing child's `files`/`annotations` entry from the sidecars
  on disk — a `done` child without them fails `assemble` loud) and re-run
  `assemble --seeded` over it to refresh `artifacts[]`. Files a re-dispatched child later
  superseded remain in the run's scratch workdir only — not in the sidecars, so never promoted.

**4.4 Semantic gate (gating)** — runs on EVERY finalize that reaches a clean 4.3 gate (not only on
a first delivery; closes the gap where a module that failed C on attempt 1 — promoted-on-fail, then
re-authored on a later pass — would otherwise never be semantically reviewed):

Dispatch N `Task(run_in_background=True)`, one per `manifest.children[]`, per
`references/rtl-review-task-contract.md` (paths only: child `files[]` + the child's per-child doc resolved
via `manifest.children[].doc` + design.md §1.4 slice; you read no RTL). Dispatch, then reap on wake.
Aggregate into `{workdir}/semantic-review.json` (schema `references/semantic-review.schema.json`):
- `STATUS: DONE` + valid finding JSON → fold its findings in (each carries reviewer-assigned
  `fix_locus ∈ {rtl, spec}`).
- `STATUS: BLOCKED` OR malformed/unparseable JSON → record a `{child, severity:"minor",
  category:"unavailable", location:"-", summary:"review unavailable: <reason>"}` finding (the
  `unavailable` marker is the only finding with no `fix_locus`) — never silently treated as ok, but a
  DISTINCT category from substantive concerns.

Run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py validate-review --review {workdir}/semantic-review.json
```

On a non-zero exit, re-assemble the JSON and re-run (this is a main-thread fix, NOT a re-dispatch). On
exit 0 it prints a one-line gate verdict `{"gate":"trip"|"clear","flagged":[{child,category,severity,
fix_locus}…],"loci":{"rtl":[…],"spec":[…]},"spec_confidence":"high"|"medium"|"low"|null}` — the
mechanical `category × severity` reduction partitioned by `fix_locus`, computed by the script, not
judged by eye (the same reduction Step 4.5's `finalize` re-computes in-process and writes verbatim as
`stage_specific.semantic_gate`). `spec_confidence` is the **minimum** `confidence` over every
`fix_locus=spec` finding (reviewer-reported, defaulting to `low` if omitted; `null` when `loci.spec` is
empty) — rtl-design has no triage re-check, so this is the sole trust signal the kernel's upstream
route reads on a spec-locus trip. Then apply the verdict:

- **`gate=clear`** → proceed to 4.5 (pass path); `finalize` lists `semantic-review.json` in `artifacts[]`.
  Advisory findings (`over-engineering` any severity, `minor`, `unavailable`) never trip — recorded,
  with a `⚠ <child> <category>` line in the completion summary.
- **`gate=trip`** → disposition by locus (mirroring the 4.3 self-converge loop):
  - **`loci.rtl` non-empty (rtl-local intent defect) → self-converge in-stage** (same mechanic as 4.3): re-dispatch only the flagged children (reduced fan-out, `references/child-task-contract.md` — the same authoring contract 4.3 re-dispatches, injecting that child's semantic findings as fix-scope feedback), re-run `assemble --seeded`, then **re-run the 4.4 semantic-review wave** (`references/rtl-review-task-contract.md`) and re-apply the verdict. The fixer edits only its own child's RTL — `design.md` / `<child>.md` are the immovable intent boundary (Iron Rule), so the intent source is never touched. **Exit:** the re-run gate reaches `clear` (converged) or a re-dispatched child returns `STATUS: BLOCKED` (it judges the fix needs upstream / exceeds its authority) → that round's `assemble` blocked-child precedence stops the stage `status=fail`. **No round cap** (exactly as 4.3).
  - **`loci.spec` non-empty (spec-rooted — this child's RTL cannot fix it) → fail-out**: proceed to 4.5; `finalize` folds the trip into `status=fail` with `fail_reason` `"semantic gate: spec-rooted intent defect — <child>"`, carrying `stage_specific.semantic_gate.{loci.spec, spec_confidence}` so the kernel routes it upstream (to `specification` on high confidence, else escalate).
  - **both non-empty** → self-converge the rtl-locus children first; any `loci.spec` findings remaining after convergence then fail-out per the spec-locus rule.
  (the first `flagged[]` child names the `fail_reason`; if more than one is flagged, ` (+N more)` is appended.)
- **Review unavailable** (the whole wave is unusable — no `semantic-review.json` assemblable at all, e.g. total dispatch failure; per-child `BLOCKED`/malformed is already handled by the aggregation above) → do NOT gate; write the minimal `semantic-review.json` with one `unavailable` finding (validator reports `gate=clear`), note it in the completion summary, and proceed to 4.5.
- **Verdict integrity:** you MUST NOT override a `gate=trip` to pass.

**4.5 Build `result.json`** (`{workdir}/result.json`; schema `references/result.schema.json` + envelope):

Run the finalize subcommand after the 4.2 exit gate, the 4.3 conformance gate (converged), and the 4.4
semantic-review wave have completed (finalize assembles their on-disk outputs — it does NOT run the 4.3
loop or the 4.4 wave):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py finalize --workdir {workdir} --module {module} --top <top_module> --manifest <manifest>
```

`finalize` re-derives the exit verdict in-process over the converged sidecars (`status` + `fail_reason` +
`artifacts[]`, verbatim) and folds in the semantic gate from `semantic-review.json` (its verdict =
`stage_specific.semantic_gate`, verbatim — including `spec_confidence`, folded through unchanged); a
`semantic_gate=trip` flips a passing exit-verdict to
`status=fail` with a locus-tagged `fail_reason` (spec-rooted named first, else the rtl-local fallback — after §4.4's rtl-locus self-converge loop a pure rtl-locus trip has already converged to `clear` or failed via `assemble` blocked-child precedence before reaching this fold, so the reason folded here is normally spec-rooted). It adds
`top_module` (= `manifest.module`, audit-only) and writes the complete envelope; the free-text run
narration is NOT in result.json (it belongs in events.jsonl). Exit 0 = result.json written (status pass
or fail). A non-zero finalize exit is a program exception (BLOCKED).

A 4.2 exit gate that already failed writes its own `status=fail` and stops there (it copies the
`assemble` exit-gate verdict — including a mid-loop round's blocked-child or topology fail) — finalize is
reached only when the exit gate passes through to the semantic gate. In the completion summary, emit one line
`semantic-gate: <clear | trip | unavailable>; see semantic-review.json`; if any `semantic-review.json`
finding is `severity=critical` (possible on a cleared gate when the critical finding is a non-gating
category, e.g. `over-engineering`), add `⚠ <child>
critical <category> finding — recommend operator review before downstream`.

rtl-design failures route by fix-locus: **upstream / architecture / intent** defects (exit-gate topology,
`<child>.md §2` incomplete, PPA, `build_*` error, or a **spec-locus** semantic-gate trip) yield
`status=fail` + a locus-tagged `fail_reason` — a spec-locus semantic trip additionally carries
`semantic_gate.{loci.spec, spec_confidence}` for the kernel's upstream route. **Child-authoring** defects
self-converge in-stage by re-dispatch: a presence defect (`check-conformance` violations, fix-locus=child)
in Step 4.3's loop, and an **rtl-locus semantic-gate trip** in Step 4.4's self-converge loop — in both, a
re-dispatched child that returns `BLOCKED` fails that round's `assemble` (blocked-child precedence) →
`status=fail`. You remain a pure dispatcher: every fix lands through a child re-dispatch, never a
main-thread edit of RTL or intent.

## Red Flags

| Excuse | Reality |
|---|---|
| "Timing won't close — I'll just adjust the architecture in the RTL to hit PPA" | The module-level `design.md` + per-child `<child>.md §1–§5` are an immovable boundary this round. If the fix would cross either, stop: write `status=fail` and exit. RTL-level adjustments do not override architectural decisions. |
| "This nearby file isn't in the trigger but it's obviously related — I'll fix it too" | During rework, modify only the files in the trigger's `violations[]` / the `map_to_child` set. Touching anything outside is a prohibited operation. |

## Pitfalls

| Mistake | Fix |
|---|---|
| `rtl-files.json` is out of sync with the RTL files on disk | `assemble` writes it from the reaped reports; if out of sync, re-run `assemble` (the main thread never edits it directly). |
| A child reports no annotations by omitting the category | Every SGDC/SDC category is present with an explicit `[]`; an omitted category and "none" are not the same claim, and the schema rejects the omission. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written (the framework validates it against the schema at stage completion; this gate does not re-run that check).
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] **Exit gate:** the `assemble` exit-gate exited 0 (or its fail verdict was written); `finalize` wrote the envelope from it (it owns `status` / `artifacts[]`; this gate does not restate the formula).
- [ ] `{workdir}/rtl-files.json` and `{workdir}/constraint-annotations.json` were written by `assemble`.
- [ ] **Conformance gate:** `check-conformance` exited 0 (or self-converged); a blocked re-dispatched child fails that round's `assemble` (blocked-child precedence) → the verdict was copied to `result.json` `status=fail`.
- [ ] **Semantic gate (every clean-gate finalize):** the review wave ran, `semantic-review.json` was written + self-validated, the gate verdict was applied (clear → proceed; trip → locus-split per §4.4: an rtl-locus trip self-converges via child re-dispatch, a spec-locus / exhausted-BLOCKED trip → `status=fail` + locus-tagged `fail_reason` carrying `semantic_gate.{loci.spec, spec_confidence}`), and the `finalize` verb wrote `semantic_gate` + `semantic-review.json` into the envelope; BLOCKED/malformed reviewers recorded as "review unavailable" (not silently ok), so do NOT gate; a `gate=trip` was never overridden to pass.

## Return Contract

Main-thread skill: control returns directly to the caller; the caller decides based on `{workdir}/result.json`. There is no Task-subagent `STATUS:` last-line signal from this skill itself.

Each dispatched per-child sub-Task ends with a harness-level `STATUS: DONE` + a `{"files": [...], "incdirs"?: [...], "annotations": {...}}` JSON line, or `STATUS: BLOCKED <reason>` (schema in `references/child-task-contract.md`).

These signals are consumed by the rtl-design main thread (translated into `reaped-children.json` for the finalize scripts), not by the caller. The caller only reads this skill's `result.json` envelope (`status ∈ {pass, fail}`).

### Re-entry and completion

Your sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`; a missing `result.json` is treated as incomplete (no cross-session "already complete" flag). The framework's `carry_self` never carries the gate review (`semantic-review.json`) forward on a repair — invalidate-on-rework. Every re-entry re-runs the semantic gate (Step 4.4) on the current RTL before finalize — the affected children re-dispatch and the gate runs on every clean-exit-gate finalize — so a compaction resumes without losing work and a stale `clear` cannot survive to finalize. There is no human review loop: control returns to the caller, which decides on `result.json`.

## Bundled References

- [`references/child-task-contract.md`](references/child-task-contract.md) — the per-child sub-Task prompt + returned annotation schema (dispatched in Step 3).
- [`references/coding-rules.md`](references/coding-rules.md) — RTL coding rules (naming / ports / clocks / resets / FSM / RAM / low-power / datapath).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md) — per-child semantic review sub-Task contract (gating; dispatched in Step 4.4).
- [`references/semantic-review.schema.json`](references/semantic-review.schema.json) — schema for the aggregated `semantic-review.json`.
