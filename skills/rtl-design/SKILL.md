---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, maintaining filelist, or recording top module + constraint annotations in README.md; not for verification, lint, or synthesis.
---

# RTL Design

Your sole responsibility: orchestrate per-child RTL authoring as a pure dispatcher over `manifest.json`'s child roster: the per-child sub-Tasks author the RTL; deterministic finalize scripts then produce `filelist.txt`, `README.md` (top-module declaration + SGDC/SDC constraint-annotation notes), the `.child_reports.json` ledger, and `result.json` from their reaped reports. You never author or read RTL yourself.

**Load mode:** this skill runs main-thread, invoked via `Skill(veripower:rtl-design)` by its caller (not dispatched as a Task subagent). It uses the Task tool for one fan-out wave (one Level-1 sub-Task per child unit, including the top-integration child); finalize is then deterministic main-thread scripts, not a sub-Task. You never author RTL inline.

## When to Use

- Write new RTL for a module.
- Modify existing RTL (bug fix, PPA tuning, or architecture change).
- Maintain `filelist.txt` or the RTL directory structure.
- Record the top-module declaration and SDC / SGDC constraint-annotation notes in `README.md`.

## Iron Rule

- Every RTL file on disk MUST appear in `filelist.txt` (contract violation — a missing `filelist.txt` entry hides source files from consumers).
- **No child RTL in the main thread:** every child (including the top-integration child) is dispatched in the fan-out wave. You consume each sub-Task's `files[]` paths only (the scripts aggregate them into `filelist.txt`) and **MUST NOT read the dispatched child's** `.v`/`.sv` content back into your context — child RTL would otherwise compound across the long-lived main thread. There is no inline TOP authoring: even a single child is written by a sub-Task.
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

| Path | Schema / Format | Use |
|---|---|---|
| `Design/specification/design.md` | Custom markdown | Module-level design. Passed by path to the child sub-Tasks, read-scope limited to the §1.4.1/§1.4.2/§1.6 tables (`references/child-task-contract.md`); the main thread does not read it. |
| `Design/specification/manifest.json` | JSON (`{module, children:[{name, doc, rtl_modules, brainstorm_anchor, role}]}`) | Child roster — drives the fan-out `N = len(children[])` (every child, incl. the top-integration child). |
| `Design/specification/<child>.md` × N | Custom markdown (frontmatter + §1–§5) | Per-child sub-design: frontmatter (`ports` / `clocks` / `features` / `file_path`) + §2 Interface / §3 Internal Behavior drive per-child RTL derivation. |

When `{failing_result}` is injected, read additional context from the same directory as the trigger file: when the trigger carries `violations[]` / `ppa_actual[]`, they are the primary inputs (a trigger without them — e.g. coverage-rooted — falls back to Step 2's module-wide mapping). When a PPA dimension is present (`ppa_actual` non-empty), also read the sibling `reports/` or `reports_*/` subdirectory (`timing_*.rpt` / `area.rpt` / `power_*.rpt`) to locate the bottleneck down to the RTL module. The specific read scope is driven by the trigger's content; do not enumerate it ahead of time.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `<top_module>.v` | Verilog-2001 | Top integration RTL — authored by the top-integration child sub-Task, never the main thread. |
| `*.v` (per child; `*.vh` headers) | Verilog-2001 | Each child writes its `rtl_modules[]` into `.v` files of its own choosing (spec defines modules, not layout); the child's returned `files[]` is authoritative. **STRICT Verilog-2001** — a `.sv` extension or any SystemVerilog-only construct (`logic`/`always_ff`/`typedef`/…) is rejected by `check-conformance`'s dialect gate, because the kernel's downstream `rtl` selectors match `*.v` alone (a `.sv` artifact silently drops out of the dependency graph). |
| `filelist.txt` | text (`#` comments + `+incdir+` + file path list) | Compile / synthesis input list — generated by `assemble` from the ledger. |
| `README.md` | Custom markdown | `**Top module**: <top_module>` line + constraint-annotation note (SGDC + SDC) — generated by `assemble`. |
| `.child_reports.json` | JSON ledger (`{<child>: {files, incdirs?, annotations}}`) | Reaped-report ledger — generated by `assemble`; the `seed` verb carries it forward into a later repair run. |
| `semantic-review.json` | `references/semantic-review.schema.json` | Gating per-child intent review (Step 4.4), aggregated by the main thread on every clean-gate finalize. |

The promoted full set is enumerated by `rtl finalize` — this table is the contract surface, not a mirror of it.

## Workflow (pure-orchestrator; one fan-out wave + scripted finalize)

### Fan-out Dispatch Contract

Framework-mechanism rules (dispatch-and-wait below is the main-thread lifecycle); enforced at the
framework / harness layer (the wake protocol; writes confined to `runs/N/`, promoted on reap), not by this skill's
Completion Gate.

- **No Level 2 dispatch:** this skill dispatches only Level-1 per-child sub-Tasks — the audit boundary.
- **Dispatch-and-wait:** after dispatching the fan-out wave's sub-Tasks, send a brief status and
  end the turn; the harness wakes the main thread per completion (the wake is to the harness, not
  back to the caller). Reap each, and finalize only after all dispatched children have
  reported — never against a partial set.
- **No `kernel.py`:** this skill does not call `kernel.py`.
- **Sub-Task `STATUS: BLOCKED` carve-out:** a sub-Task's last-line `STATUS: BLOCKED <reason>` is a
  harness-level signal, distinct from the `result.json.status` enum (`pass`/`fail` only); the
  main thread maps it to `status=fail` + `fail_reason` and defers re-dispatch to a later repair
  dispatch.

### Step 1: Read inputs, seed, determine scope

Read `manifest.json` (`.module` =
`<top_module>`; the `children[]` dispatch roster: `name` + `doc` + `rtl_modules[]`). Nothing else is
read up front — no `design.md`, no `<child>.md` body, no RTL, and no upstream `result.json`;
the per-child sub-Tasks read their own docs. (Step-1 source 3 below consults `{workdir}/changed-inputs.md`
for scope when present.)

Run `seed` (it internally handles both the canonical-present and first-delivery cases):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py seed --workdir {workdir}
```

The `seed` verb derives the canonical dir as `{workdir}/../..` (no hardcoded per-module path here)
and carries unchanged children's RTL + `filelist.txt` / `README.md` + the prior
`.child_reports.json` ledger forward (whitelist = HDL suffixes at any depth ∪ every file
the ledger's `files` entries list — children's non-HDL support files are products too;
**no-clobber**, so any freshly-authored workdir residue is kept — never `result.json` or
`semantic-review.json`; Step 4.4 re-judges here). With no canonical (a first delivery) it is a no-op.

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
   → module-wide). If it is absent or empty but `seed` carried a prior canonical (a re-verify, not a
   first delivery), re-author no child: re-run Step 4's gate on the seeded RTL and finalize; every
   file stays byte-identical.
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

After dispatching, end the turn and wait for the harness wake.
On wake-up, reap each dispatched child's harness `STATUS:` last line + its JSON line. Proceed to
Step 4 only after every dispatched child has reported (DONE or BLOCKED); if woken with fewer reports
than dispatched, keep waiting (do not finalize against a partial report set).

### Step 4: Finalize (scripts + gates + semantic gate) + result.json

**4.1 Serialize reaped reports → `{workdir}/fresh_reports.json`** — your single transcription act: the
finalize scripts read only disk, not your reap context, so dump each reaped child's `STATUS` + JSON to this
one file for them (`STATUS: DONE`+JSON → `{"status":"done",...}`; `STATUS: BLOCKED <r>` →
`{"status":"blocked","reason":"<r>"}`). A straight copy, no judgment.

**4.2 Build + exit gate** (`<manifest>` = `Design/specification/manifest.json`; `<top_module>` =
`manifest.module`; `<design>` = `Design/specification/design.md`):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py assemble --workdir {workdir} --manifest <manifest> --top <top_module> [--seeded]
```

`assemble` builds the ledger/filelist/README and runs the post exit-gate in one step. A **build error**
(malformed reports/ledger) yields a non-zero exit with a stderr message and **no stdout verdict** (distinct
from a gate-fail verdict); hand-write `{workdir}/result.json` as a `status=fail` envelope with the stderr as
`fail_reason`, and stop. Otherwise it prints the exit-gate verdict JSON on stdout; exit code = truth
(topology + blocked-child); a fail verdict stops the stage — Step 4.5's `finalize` writes it into
`result.json`. (`--seeded` whenever `seed` carried a prior baseline — canonical existed — never on a first delivery's initial build.)

**4.3 Conformance gate + self-converge loop** (deterministic; runs EVERY invocation):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py check-conformance --workdir {workdir} --manifest <manifest> --top <top_module> --ledger {workdir}/.child_reports.json --design <design>
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
  `fresh_reports.json` evicts every already-passing child via `merge_filter`'s roster∩fresh), then
  `check-conformance`. `assemble`'s verdict is authoritative every round exactly as in 4.2 — a non-zero
  `assemble` (blocked-child or topology) stops the stage with `status=fail` and does not fall through to
  `check-conformance`; otherwise loop until `check-conformance` passes. The loop is intra-stage scratch —
  the stage produces one result at exit, the re-dispatches are not externally visible, and no persistent
  "pending finalize" state carries across.
- On convergence, rebuild a full-roster `fresh_reports.json` (all children `status=done`,
  reconstructing each already-passing child's `files`/`annotations` entry from the current
  `.child_reports.json` ledger — a `done` child without them fails `assemble` loud) and re-run
  `assemble --seeded` over it + the converged ledger to refresh `artifacts[]`. Files a re-dispatched
  child later superseded remain in the run's scratch workdir only — not in the ledger, so never promoted.

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
- `verdict="concerns"` iff any finding with category ≠ `unavailable`; `has_critical` iff any
  `severity=critical`.

Run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py validate-review --review {workdir}/semantic-review.json
```

On a non-zero exit, re-assemble the JSON and re-run (this is a main-thread fix, NOT a re-dispatch). On
exit 0 it prints a one-line gate verdict `{"gate":"trip"|"clear","flagged":[{child,category,severity,
fix_locus}…],"loci":{"rtl":[…],"spec":[…]}}` — the mechanical `category × severity` reduction
partitioned by `fix_locus`, computed by the script, not judged by eye (the same reduction Step 4.5's
`finalize` re-computes in-process and writes verbatim as `stage_specific.semantic_gate`). Then apply the
verdict:

- **`gate=clear`** → proceed to 4.5 (pass path); `finalize` lists `semantic-review.json` in `artifacts[]`.
  Advisory findings (`over-engineering` any severity, `minor`, `unavailable`) never trip — recorded,
  with a `⚠ <child> <category>` line in the completion summary.
- **`gate=trip`** → proceed to 4.5: `finalize` folds the trip into `status=fail` with a locus-tagged
  `fail_reason` (a gate trip stops the stage out, exactly as the 4.2/4.3 gate fails do) —
  `"semantic gate: spec-rooted intent defect — <child>"` when `loci.spec` is non-empty, else
  `"semantic gate: rtl-local intent defect — <child>"` (the first `flagged[]` child; if more than one is
  flagged, ` (+N more)` is appended).
- **Review unavailable** (the whole wave is unusable — no `semantic-review.json` assemblable at all, e.g. total dispatch failure; per-child `BLOCKED`/malformed is already handled by the aggregation above) → do NOT gate; write the minimal `semantic-review.json` with one `unavailable` finding (validator reports `gate=clear`), note it in the completion summary, and proceed to 4.5.
- **Verdict integrity:** you MUST NOT override a `gate=trip` to pass.

**4.5 Build `result.json`** (`{workdir}/result.json`; schema `references/result.schema.json` + envelope):

Run the finalize subcommand after the 4.2 exit gate, the 4.3 conformance gate (converged), and the 4.4
semantic-review wave have completed (finalize assembles their on-disk outputs — it does NOT run the 4.3
loop or the 4.4 wave):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/rtl/__main__.py finalize --workdir {workdir} --module {module} --top <top_module> --manifest <manifest>
```

`finalize` re-derives the exit verdict in-process over the converged ledger (`status` + `fail_reason` +
`artifacts[]`, verbatim) and folds in the semantic gate from `semantic-review.json` (its verdict =
`stage_specific.semantic_gate`, verbatim); a `semantic_gate=trip` flips a passing exit-verdict to
`status=fail` with a locus-tagged `fail_reason` (spec-rooted named first, else rtl-local). It adds
`top_module` (= `manifest.module`, audit-only) and writes the complete envelope; the free-text run
narration is NOT in result.json (it belongs in events.jsonl). Exit 0 = result.json written (status pass
or fail). A non-zero finalize exit is a program exception (BLOCKED).

A 4.2 exit gate that already failed writes its own `status=fail` and stops there (it copies the
`assemble` exit-gate verdict — including a mid-loop round's blocked-child or topology fail) — finalize is
reached only when the exit gate passes through to the semantic gate. In the completion summary, emit one line
`semantic-gate: <clear | trip | unavailable>; see semantic-review.json`; if `has_critical` (possible on a
cleared gate when the critical finding is a non-gating category, e.g. `over-engineering`), add `⚠ <child>
critical <category> finding — recommend operator review before downstream`.

rtl-design failures route by fix-locus: **upstream / architecture / intent** defects (exit-gate topology,
`<child>.md §2` incomplete, PPA, `build_*` error, or any semantic-gate trip) yield `status=fail` + a
locus-tagged `fail_reason`, operator-driven — you stay a pure dispatcher and do not self-loop; a
**child-authoring presence defect** (`check-conformance` violations) is fix-locus=child and self-converges
in Step 4.3's loop, while a blocked re-dispatched child fails that round's `assemble` (blocked-child
precedence) → `status=fail`.

## Red Flags

| Excuse | Reality |
|---|---|
| "Timing won't close — I'll just adjust the architecture in the RTL to hit PPA" | The module-level `design.md` + per-child `<child>.md §1–§5` are an immovable boundary this round. If the fix would cross either, stop: write `status=fail` and exit. RTL-level adjustments do not override architectural decisions. |
| "This nearby file isn't in the trigger but it's obviously related — I'll fix it too" | During rework, modify only the files in the trigger's `violations[]` / the `map_to_child` set. Touching anything outside is a prohibited operation. |

## Pitfalls

| Mistake | Fix |
|---|---|
| `filelist.txt` is out of sync with the RTL files on disk | the `assemble` verb generates `filelist.txt` from the ledger; if out of sync, re-run `assemble` (the main thread never edits it directly). |
| `filelist.txt` uses `//` comments | SpyGlass does not recognize `//` comments; use `#` only. |
| `README.md` is missing the `**Top module**: <top_module>` line | the `assemble` verb writes the `**Top module**: <top_module>` line; if absent, re-run `assemble` (check its stderr on a non-zero exit). |
| Constraint-annotation note not recorded | `README.md` MUST record both the SGDC and SDC sections. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written (the framework validates it against the schema at stage completion; this gate does not re-run that check).
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] **Exit gate:** the `assemble` exit-gate exited 0 (or its fail verdict was written); `finalize` wrote the envelope from it (it owns `status` / `artifacts[]`; this gate does not restate the formula).
- [ ] `{workdir}/.child_reports.json`, `{workdir}/filelist.txt`, and `{workdir}/README.md` were generated by the scripts (ledger / filelist / README respectively).
- [ ] **Conformance gate:** `check-conformance` exited 0 (or self-converged); a blocked re-dispatched child fails that round's `assemble` (blocked-child precedence) → the verdict was copied to `result.json` `status=fail`.
- [ ] **Semantic gate (every clean-gate finalize):** the review wave ran, `semantic-review.json` was written + self-validated, the gate verdict was applied (clear → proceed; trip → `status=fail` + locus-tagged `fail_reason`, **no in-skill autofix**), and the `finalize` verb wrote `semantic_gate` + `semantic-review.json` into the envelope; BLOCKED/malformed reviewers recorded as "review unavailable" (not silently ok), so do NOT gate; a `gate=trip` was never overridden to pass.

## Return Contract

Main-thread skill: control returns directly to the caller; the caller decides based on `{workdir}/result.json`. There is no Task-subagent `STATUS:` last-line signal from this skill itself.

Each dispatched per-child sub-Task ends with a harness-level `STATUS: DONE` + a `{"files": [...], "incdirs"?: [...], "annotations": {...}}` JSON line, or `STATUS: BLOCKED <reason>` (schema in `references/child-task-contract.md`).

These signals are consumed by the rtl-design main thread (translated into `fresh_reports.json` for the finalize scripts), not by the caller. The caller only reads this skill's `result.json` envelope (`status ∈ {pass, fail}`).

### Re-entry and completion

Your sole on-disk completion signal is `{workdir}/result.json` present with `status=pass`; a missing `result.json` is treated as incomplete (no cross-session "already complete" flag). `rtl seed` never clobbers workdir residue but never carries the gate review (`semantic-review.json`) forward — invalidate-on-rework. Every re-entry re-runs the semantic gate (Step 4.4) on the current RTL before finalize — the affected children re-dispatch and the gate runs on every clean-exit-gate finalize — so a compaction resumes without losing work and a stale `clear` cannot survive to finalize. There is no human review loop: control returns to the caller, which decides on `result.json`.

## Bundled References

- [`references/child-task-contract.md`](references/child-task-contract.md) — the per-child sub-Task prompt + returned annotation schema (dispatched in Step 3).
- [`references/coding-rules.md`](references/coding-rules.md) — RTL coding rules (naming / ports / clocks / resets / FSM / RAM / low-power / datapath).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md) — per-child semantic review sub-Task contract (gating; dispatched in Step 4.4).
- [`references/semantic-review.schema.json`](references/semantic-review.schema.json) — schema for the aggregated `semantic-review.json`.
