---
name: rtl-design
description: Use when writing or modifying Verilog/SystemVerilog RTL, maintaining filelist, or recording top module + constraint annotations in README.md; not for verification, lint, or synthesis.
---

# RTL Design

This skill's sole responsibility: **orchestrate** per-child RTL authoring as a pure dispatcher. The main thread reads only `manifest.json` + specification's `result.json`, runs **one** fan-out wave (one sub-Task per child unit, including the top-integration child), then runs deterministic finalize **scripts** over the reaped reports and writes `result.json`. Per-child RTL (one or more `.v`/`.sv` per child) is produced by the sub-Tasks; `filelist.txt`, `README.md` (top-module declaration + SGDC/SDC constraint-annotation notes), and the `.child_reports.json` ledger are produced by scripts. The main thread never authors RTL, never reads `design.md`, and never reads child RTL.

**Load mode:** this skill runs main-thread, invoked via `Skill(veripower:rtl-design)` by its caller (not dispatched as a Task subagent). It uses the Task tool for **one** fan-out wave (one Level-1 sub-Task per child unit, including the top-integration child); finalize is then deterministic main-thread **scripts**, not a sub-Task. The main thread never authors RTL inline.

## When to Use

- Write new RTL for a module.
- Modify existing RTL (bug fix, PPA tuning, or architecture change).
- Maintain `filelist.txt` or the RTL directory structure.
- Record the top-module declaration and SDC / SGDC constraint-annotation notes in `README.md`.

## Iron Rule

- Every RTL file on disk MUST appear in `filelist.txt` (contract violation — a missing `filelist.txt` entry hides source files from consumers).
- **No child RTL in the main thread:** every child (including the top-integration child) is dispatched in the fan-out wave. The main thread consumes each sub-Task's `files[]` paths only (the scripts aggregate them into `filelist.txt`) and **MUST NOT read the dispatched child's** `.v`/`.sv` content back into the main-thread context — child RTL would otherwise compound across the long-lived main thread. There is no main-thread TOP authoring: even a single child is written by a sub-Task, never by the main thread.
- **No whole-design elaboration in any child sub-Task:** per `references/child-task-contract.md`, no child may whole-design elaborate/compile, read sibling RTL bodies, or reverse-read an external verification harness; integration/elaboration correctness is verified by downstream verification. A unit child may best-effort `verilator --lint-only` its own module only.
- **`<child>.md §2 Interface` incomplete:** if the interface spec is missing or underspecified, write `status=fail` + `fail_reason="<child>.md §2 Interface incomplete"`; do not invent interfaces.
- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

## Input Artifacts

### Context variables

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root. |
| `{module}` | Module name. |
| `{rework_trigger}` | Optional. Caller-injected trigger-context file path; contains `stage_specific.violations[]` / `ppa_actual[]` and related context for this rework round. Its presence distinguishes the rework branch from the first-run and incremental-update branches. |
| `{orchestrator_context_path}` | Optional. Caller-injected fix-scope hint file path. When present, narrows the modification scope more precisely than `{rework_trigger}.violations[]` alone. |

### External reference inputs

| Path | Schema / Format | Required | Use |
|---|---|---|---|
| `Design/specification/result.json` | `skills/specification/references/result.schema.json` | required (first-run) | envelope + ppa_targets |
| `Design/specification/design.md` | Custom markdown | required (first-run) | Module-level design (overview §1.1–1.6, §1.4.1 Top-Level IO table, §1.4.2 Inter-module Interconnects). The main thread passes its path to the child sub-Tasks with the read-scope limited to the §1.4.1/§1.4.2/§1.6 tables (see `references/child-task-contract.md`); it does not read it. Per-submodule content lives in each `<child>.md`; iterate `manifest.children[]`. |
| `Design/specification/manifest.json` | JSON (`{module, children:[{name, doc, rtl_modules, brainstorm_anchor, role}]}`) | required | Child unit roster (`children[].name`, `children[].doc`, `children[].rtl_modules[]`) — drives the fan-out roster `N = len(manifest.children[])` (every child, including the top-integration child). |
| `Design/specification/<child>.md` × N | Custom markdown (frontmatter + §1–§5) | required | Per-child sub-design file. Frontmatter carries `ports` (§1.4.2 cut-edges, derived) / `clocks` (§1.6) / `features` / `file_path`; §2 Interface + §3 Internal Behavior carry unit-internal interface + microarchitecture for per-child RTL derivation. |
| `Design/specification/constraints/<TOP>.{sdc,sgdc}` | SDC + SGDC | required (first-run) | Constraint source of truth (one pair). |

When `{rework_trigger}` is injected, read additional context from the same directory as the trigger file: `stage_specific.violations[]` / `ppa_actual[]` are the primary inputs. When a PPA dimension is present (`ppa_actual` non-empty), also read the sibling `reports/` or `reports_*/` subdirectory (`timing_*.rpt` / `area.rpt` / `power_*.rpt`) to locate the bottleneck down to the RTL module. The specific read scope is driven by the trigger's content; do not enumerate it ahead of time.

## Output Artifacts

| Path (relative to `{workdir}`) | Schema / Format | Use |
|---|---|---|
| `result.json` | `references/result.schema.json` + envelope | This stage's status contract. |
| `<top_module>.v` / `.sv` | Verilog-2001 / SystemVerilog | Top integration RTL — authored by the **top-integration child sub-Task** (the child whose `rtl_modules[]` contains `top_module`), never by the main thread. |
| `*.v` / `*.sv` (per child) | Verilog-2001 / SystemVerilog | Each child writes its `rtl_modules[]` into **one or more** `.v`/`.sv` files of its own choosing — specification defines RTL modules, not file layout, so one file may hold multiple modules. The child's returned `files[]` is the authoritative file list. |
| `filelist.txt` | text (`#` comments + `+incdir+` + file path list) | Compile / synthesis input list — generated by **`build_filelist.py`** from the ledger. |
| `README.md` | Custom markdown | The `**Top module**: <top_module>` line + the constraint-annotation note (SGDC + SDC sections) — generated by **`build_readme.py`** from the ledger + `--top`. |
| `.child_reports.json` | JSON ledger (`{<child>: {files, incdirs?, annotations}}`) | The reaped-report ledger — generated by **`build_ledger.py`** (merge fresh reports onto any seeded ledger, filter to the manifest roster, shape-validate). Source for `build_filelist.py` / `build_readme.py`. |
| `semantic-review.json` | `references/semantic-review.schema.json` | Per-child intent-review findings (every clean-gate finalize; **gating** — Step 4.4 semantic gate) — aggregated by the main thread from the review wave. |

## Workflow (pure-orchestrator; one fan-out wave + scripted finalize)

### Fan-out Dispatch Contract

Framework-mechanism rules (the subagent-side prohibitions echo `stage-subagent.md.tpl`; dispatch-and-wait below is the main-thread lifecycle); enforced at the
framework layer (verify.py isolation gate + harness wake protocol), **not** by this skill's
Completion Gate.

- **No Level 2 dispatch:** this skill may dispatch Level-1 per-child sub-Tasks, but a dispatched
  sub-Task MUST NOT call the Task tool (audit boundary).
- **Dispatch-and-wait:** after dispatching the fan-out wave's sub-Tasks, send a brief status and
  end the turn; the harness wakes the main thread per completion (the wake is to the harness, not
  back to the caller). Reap each, and finalize only after **all** dispatched children have
  reported — never against a partial set.
- **No `state.py`:** this skill does not call `state.py`.
- **Sub-Task `STATUS: BLOCKED` carve-out:** a sub-Task's last-line `STATUS: BLOCKED <reason>` is a
  **harness-level** signal, distinct from the `result.json.status` enum (`pass`/`fail` only); the
  main thread maps it to `status=fail` + `fail_reason` and defers re-dispatch to trigger-driven
  rework.

### Step 1: Read inputs, select branch, seed if needed

Read `Design/specification/result.json` (envelope + `stage_specific.top_module`) and
`manifest.json` (the `children[]` dispatch roster: `name` + `doc` + `rtl_modules[]`). On first-run
the main thread reads **nothing else** — no `design.md`, no `<child>.md` body, no RTL.

Based on whether `{rework_trigger}` is injected and whether the canonical path
`Design/rtl-design/{*.v,*.sv,filelist.txt}` already holds prior RTL artifacts, choose one of three
branches:

- **Trigger-driven rework** (`{rework_trigger}` injected): see Step 2 for the `map_to_child` sketch.
  - Read the trigger's `stage_specific.violations[]` and `ppa_actual[]` (if present); modify only the
    files listed in `violations`. Modifying anything outside the violations list is a prohibited
    operation (see Red Flags). If the trigger file is unreadable, write `result.json` with
    `status=fail` and `stage_specific.fail_reason="rework_trigger not readable"`, then exit.
  - PPA dimension: when `ppa_actual` is non-empty, also read the trigger's sibling `reports/` or
    `reports_*/` subdirectory to locate the bottleneck RTL module.
  - The module-level `design.md` + per-child `<child>.md` set are an immovable boundary, not modified.
    If the rework plan would violate either layer, stop this round (see Red Flags).
- **Incremental-update branch** (no trigger; canonical path already has prior RTL artifacts): read the
  `Design/specification/result.json` diff to determine the incremental scope, then proceed to Step 3 with the identified scope.
- **First-run branch** (no trigger; canonical path has no prior RTL artifacts): proceed to Step 3.

On the **incremental/rework** branches (canonical holds prior artifacts), run:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/seed_rework.py --workdir {workdir}
```

`seed_rework.py` derives the canonical dir as `{workdir}/../..` (no hardcoded per-module path here)
and carries unchanged children's RTL + the prior `.child_reports.json` ledger forward, no-clobber.
First-run skips it.

When `{orchestrator_context_path}` is injected, Read that sibling file first as a fix-scope hint. It
takes priority over both the trigger content (trigger-driven path) and the external-reference diff
(incremental-update path) to further narrow the modification scope.

**Pre-dispatch purity gate (fail-fast).** After reading `manifest.json` and before the Step 3
fan-out, run:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/validate_rtl_exit.py --phase pre --manifest <manifest> --top <top_module>
```

Its exit code is the truth (0 ok / 1 fail). On a non-zero exit, **assemble `{workdir}/result.json`
as a full envelope (schema `references/result.schema.json`, exactly as Step 4.5 does) with `status=fail`
+ the verdict's `fail_reason`**, and return **without dispatching** — a bundled or miscovered
top-integration child never pays authoring cost. (Step 4 re-runs `validate_rtl_exit.py`
in the default `post` phase as the backstop, where it also folds in the blocked-child precedence and
emits `artifacts`.)

### Step 2: (Rework only) map_to_child

(Only applies when `{rework_trigger}` is injected.)

1. Read `manifest.json` and the frontmatter of each `<child>.md` listed under
   `manifest.children[].doc` (Grep `^---` block only — ~15 lines per child). This frontmatter read is
   the **only** read the rework branch adds — not RTL, not `design.md`.
2. For each `violations[]` entry, map to `affected_children[]` via the most specific available key:
   - `frontmatter.file_path` matches the trigger's `file` field → that child;
   - `frontmatter.features[]` contains a feature mentioned in the violation message → that child;
   - else fall back to "module-wide" (mark all children as affected).
3. Dispatch behaviour:
   - If `affected_children[]` is a strict subset and the top-integration interconnect is unaffected:
     re-dispatch only those children (a reduced fan-out wave).
   - Else (module-wide, or a TOP-level interconnect violation): re-dispatch ALL affected children
     **including the top-integration child** (if the interconnect changed).

### Step 3: Fan-out wave

Dispatch the to-dispatch set as `Task(run_in_background=True)`, one sub-Task per child — **all
`len(manifest.children[])` children on first-run; the affected subset on rework/incremental**. Every
child (including the top-integration child) is dispatched here — no `name=="top"` special-casing, no
N==1 inline exemption (even a single child is one sub-Task). The per-child sub-Task prompt + the
returned annotation schema are in [`references/child-task-contract.md`](references/child-task-contract.md).

After dispatching, end the turn and wait for the harness wake.
On wake-up, reap each dispatched child's harness `STATUS:` last line + its JSON line. Proceed to
Step 4 only after every dispatched child has reported (DONE or BLOCKED); if woken with fewer reports
than dispatched, re-yield and keep waiting (do not finalize against a partial report set).

### Step 4: Finalize (scripts + gates + semantic gate) + result.json

**4.1 Translate reaped reports → `{workdir}/fresh_reports.json`** (unchanged: `STATUS: DONE`+JSON →
`{"status":"done",...}`; `STATUS: BLOCKED <r>` → `{"status":"blocked","reason":"<r>"}`).

**4.2 Build + topology gate** (`<manifest>` = `Design/specification/manifest.json`; `<top_module>` =
`result.json.stage_specific.top_module`; `<design>` = `Design/specification/design.md`):

```
python3 ${CLAUDE_SKILL_DIR}/scripts/build_ledger.py   --fresh {workdir}/fresh_reports.json --manifest <manifest> --out {workdir}/.child_reports.json [--seeded {workdir}/.child_reports.json]
python3 ${CLAUDE_SKILL_DIR}/scripts/build_filelist.py --ledger {workdir}/.child_reports.json --out {workdir}/filelist.txt
python3 ${CLAUDE_SKILL_DIR}/scripts/build_readme.py   --ledger {workdir}/.child_reports.json --top <top_module> --out {workdir}/README.md
python3 ${CLAUDE_SKILL_DIR}/scripts/validate_rtl_exit.py --manifest <manifest> --top <top_module> --fresh {workdir}/fresh_reports.json --ledger {workdir}/.child_reports.json
```

`build_*` non-zero exit = unexpected error → `status=fail` (stderr as `fail_reason`), stop.
`validate_rtl_exit` exit code = truth (topology + blocked-child); fail → copy its stdout verdict into
`result.json`, stop. (`--seeded` only on incremental/rework, never first-run's initial build.)

**4.3 Conformance gate + bounded self-converge loop** (deterministic; runs EVERY invocation):

```
python3 ${CLAUDE_SKILL_DIR}/scripts/check_rtl_conformance.py --workdir {workdir} --manifest <manifest> --top <top_module> --ledger {workdir}/.child_reports.json --design <design>
```

Exit 0 → go to 4.4. Exit 1 = spec↔RTL presence violations (each names a `child`; `top_instantiation`
also carries `owner_child`). These are **child-authoring defects** (fix-locus = the child), so self-converge:

- Re-dispatch set = `{v.child} ∪ {v.owner_child}` over all violations — the `owner_child` union lets a
  `top_instantiation` violation reach the sibling that renamed the module, not only the top child. The
  main thread reads the **verdict only — never the RTL**.
- Re-dispatch ONLY those children (reduced fan-out, `references/child-task-contract.md`), injecting the
  conformance verdict slice as fix-scope feedback. **Dispatch-and-wait holds per round** — the per-cycle dispatch→reap-on-wake primitive is the same one this skill's fan-out wave already uses,
  but the sequential depth here is greater than any existing skill (a rework finalize
  chains Step-3 dispatch → ≤2 loop rounds → the 4.4 review wave = up to 4 dispatch-reap cycles in one
  invocation); confirm the harness reaps across that depth at runtime.
- **Mid-loop `STATUS: BLOCKED`**: if a re-dispatched child returns `BLOCKED` in any round, do NOT let it
  fall through to the unconverged-authoring fail (`build_ledger`'s non-`done` filter would drop it and the
  stale failing entry survives via `--seeded`). After each round's reap, if any re-dispatched child is
  `BLOCKED` → stop with `status=fail` + `fail_reason` carrying the BLOCKED reason **verbatim** (an
  upstream-locus signal, routed like 4.2's blocked-child precedence — NOT authoring-convergence).
- **manifest name is authoritative**: a child MUST author its `manifest.children[].rtl_modules[]` name
  verbatim (renaming is itself a violation `check #1` catches); this precludes a `top_instantiation`
  re-dispatch oscillating between topc and a sibling that keeps renaming.
- Re-run `build_ledger` **WITH `--seeded {workdir}/.child_reports.json`** (CRITICAL — without it the
  round's subset-only `fresh_reports.json` evicts every already-passing child via `merge_filter`'s
  roster∩fresh), then `build_filelist` / `build_readme` / `check_rtl_conformance`.
- **Bounded: at most 2 re-dispatch rounds** (presence defects typically converge in 1 round; 2 gives one
  retry margin). Still failing after round 2 → `status=fail`, `fail_reason="rtl conformance unconverged
  after 2 rounds: <children+items>"`, stop. The loop is intra-stage fan-out — skill-internal scratch; the stage produces a single result at exit and the re-dispatches are not externally visible; no persistent "pending finalize" state.
- On convergence, rebuild a **full-roster** `fresh_reports.json` (all children `status=done`) and re-run
  `validate_rtl_exit --phase post` over it + the converged ledger to refresh `artifacts[]`. Round-0 files a
  re-dispatched child later superseded remain in the run's scratch workdir only — not in the ledger, so never promoted.

**4.4 Semantic gate (gating)** — runs on EVERY finalize that reaches a clean 4.3 gate (NOT
first-run-only; closes the gap where a module that failed C on attempt 1 — promoted-on-fail, then
retried incrementally — would otherwise never be semantically reviewed):

Dispatch N `Task(run_in_background=True)`, one per `manifest.children[]`, per
`references/rtl-review-task-contract.md` (paths only: child `files[]` + the child's per-child doc resolved
via `manifest.children[].doc` + design.md §1.4 slice; the main thread reads no RTL). Dispatch → reap on wake.
Aggregate into `{workdir}/semantic-review.json` (schema `references/semantic-review.schema.json`):
- `STATUS: DONE` + valid finding JSON → fold its findings in (each carries reviewer-assigned
  `fix_locus ∈ {rtl, spec}`).
- `STATUS: BLOCKED` OR malformed/unparseable JSON → record a `{child, severity:"minor",
  category:"unavailable", location:"-", summary:"review unavailable: <reason>"}` finding (the
  `unavailable` marker is the only finding with no `fix_locus`) — never silently treated as ok, but a
  DISTINCT category from substantive concerns.
- `verdict="concerns"` iff any finding **with category ≠ `unavailable`**; `has_critical` iff any
  `severity=critical`.

Run `${CLAUDE_SKILL_DIR}/scripts/validate_semantic_review.py {workdir}/semantic-review.json`
(non-zero exit → re-assemble the JSON and re-run; this is a main-thread fix, NOT a re-dispatch). On
exit 0 it prints a one-line gate verdict `{"gate":"trip"|"clear","flagged":[{child,category,severity,
fix_locus}…],"loci":{"rtl":[…],"spec":[…]}}` — the mechanical `category × severity` reduction
partitioned by `fix_locus`, computed by the script, not judged by eye. Write
`stage_specific.semantic_gate` = that parsed verdict object **verbatim** (`{gate, flagged, loci}`, no
transform — script-owned, the main thread copies it verbatim), so the result is self-describing. Then apply the verdict:

- **`gate=clear`** → list `semantic-review.json` in `artifacts[]`, proceed to 4.5 (pass path).
  Advisory findings (`over-engineering` any severity, `minor`, `unavailable`) never trip — recorded,
  with a `⚠ <child> <category>` line in the completion summary.
- **`gate=trip`** → write a complete fail `result.json` here and **stop — do not proceed to 4.5** (a
  gate fail writes its verdict and stops, exactly as the 4.2/4.3 gate fails do): `status=fail`,
  `stage_specific.semantic_gate` (written above), a locus-tagged `fail_reason` from `flagged` + `loci`
  (look up each finding's `<summary>` in the just-assembled `semantic-review.json` `findings[]` by `child`)
  — `"semantic gate: spec-rooted intent defect — <child>:<summary>"` when `loci.spec` is non-empty, else
  `"semantic gate: rtl-local intent defect — <child>:<summary>"` (use the first matching `flagged[]`
  entry; if more than one is flagged, append ` (+N more)`) — and `semantic-review.json` plus the
  already-built `filelist.txt` / `README.md` in `artifacts[]`. **No further dispatch; this skill does not
  self-loop on a semantic defect** — it is operator-driven (a `spec`-locus defect is a `design.md`
  contradiction not fixable from this child's RTL; in-skill self-heal of the `rtl`-locus case is
  deferred). The `loci` partition is informational: it tells the operator whether the fix lands in the
  child RTL (`rtl`) or `design.md` (`spec`).
- **Review unavailable** (the WHOLE wave is unusable: no `semantic-review.json` can be assembled at all
  — dispatch failure before any child reports, or an unrecoverable validate loop; individual child
  `BLOCKED`/malformed events are already handled by the aggregation bullets above, which keep the
  surviving children's findings) → do NOT gate; write the minimal `semantic-review.json` with a single
  `unavailable` finding (so the absence of a real review is a first-class artifact, not invisible — the
  validator reports `gate=clear` for it, and `stage_specific.semantic_gate` is written `clear`), note it
  in the completion summary, and proceed to 4.5.
- **Verdict integrity:** the main thread MUST NOT override a `gate=trip` to pass.

**4.5 Assemble `result.json`** (`{workdir}/result.json`; schema `references/result.schema.json` + envelope):
`status`/`artifacts` from the gates (4.2/4.3 verdict + the 4.4 **semantic gate** verdict). In the
completion summary, emit one line `semantic-gate: <clear | unavailable>; see semantic-review.json` (a
`gate=trip` does not reach 4.5 — it stops in 4.4, where its `fail_reason` is the operator-facing summary);
**if `has_critical`** (only possible on a cleared gate when the critical finding is a non-gating category,
e.g. `over-engineering`), add `⚠ <child> critical <category> finding — recommend operator review before
downstream`.

rtl-design failures route by **fix-locus**. **(1) Upstream / architecture / intent** (`validate_rtl_exit`
topology, `<child>.md §2` incomplete, PPA, `build_*` unexpected error, **or any semantic-gate trip** —
`category ∈ {missing, wrong-behavior}` at `critical`/`important`) → `status=fail` + a locus-tagged
`fail_reason`; **no internal loop, operator-driven** (the main thread stays a pure dispatcher and does not
self-loop). The semantic trip's `fail_reason` names where the fix lands via `fix_locus`: `spec` = a
`design.md` contradiction the child cannot self-fix (left for operator-driven correction); `rtl` = the
child's own RTL (the stage fails out so the operator fixes the child; in-skill self-heal of this case is
a deferred follow-up, reusing the Step-4.3 mechanic). The stage emits one `status=fail` result and does
not self-loop on a semantic defect. **(2) Child-authoring presence defect**
(`check_rtl_conformance` spec↔RTL presence violations, or a mid-loop child `BLOCKED`) → fix-locus is the
child itself, so it runs the **bounded body-blind self-converge loop** (Step 4.3: hold the verdict,
re-dispatch the failing children, re-run the scripts, ≤2 rounds); exhausting the bound (or a mid-loop
BLOCKED) falls back to (1)'s `status=fail`. The loop is intra-stage fan-out (skill-internal; re-dispatches
are not externally visible); finalize keeps no persistent "pending finalize" state — bound exhaustion is
terminal fail.

## Red Flags

| Excuse | Reality |
|---|---|
| "Timing won't close — I'll just adjust the architecture in the RTL to hit PPA" | The module-level `design.md` + per-child `<child>.md §1–§5` are an immovable boundary this round. If the fix would cross either, stop: write `status=fail` and exit. RTL-level adjustments do not override architectural decisions. |
| "This nearby file isn't in the trigger but it's obviously related — I'll fix it too" | During rework, modify **only** the files in the trigger's `violations[]` / the `map_to_child` set. Touching anything outside is a prohibited operation. |

## Pitfalls

| Mistake | Fix |
|---|---|
| `filelist.txt` is out of sync with the RTL files on disk | `build_filelist.py` generates `filelist.txt` from the ledger; if out of sync, re-run `build_filelist.py` (the main thread never edits it directly). |
| `filelist.txt` uses `//` comments | SpyGlass does not recognize `//` comments; use `#` only. |
| `README.md` is missing the `**Top module**: <top_module>` line | `build_readme.py` writes the `**Top module**: <top_module>` line; if absent, re-run `build_readme.py` (check its stderr on a non-zero exit). |
| Constraint-annotation note not recorded | `README.md` MUST record both the SGDC and SDC sections. |

## Completion Gate

- [ ] `{workdir}/result.json` has been written (the framework validates it against the schema at stage completion; this gate does not re-run that check).
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] **Exit gate:** `validate_rtl_exit.py` exited 0, and its stdout verdict was copied verbatim into `result.json`. (The script owns the R-1 top-module coverage check + child-status precedence + the RTL `artifacts[]` (Step 4.4 adds `semantic-review.json`); this gate does not restate the formula.)
- [ ] `{workdir}/.child_reports.json`, `{workdir}/filelist.txt`, and `{workdir}/README.md` were generated by the scripts (ledger / filelist / README respectively).
- [ ] **Conformance gate:** `check_rtl_conformance.py` exited 0 (or self-converged within 2 rounds); on unconverged / mid-loop BLOCKED the verdict was copied to `result.json` `status=fail`.
- [ ] **Semantic gate (every clean-gate finalize):** the review wave ran, `semantic-review.json` was written + self-validated, the script's gate verdict was applied (clear → proceed; trip → `status=fail` + locus-tagged `fail_reason`, **no in-skill autofix**), `stage_specific.semantic_gate` was written verbatim from the verdict, and `semantic-review.json` is in `artifacts[]`; BLOCKED/malformed reviewers recorded as "review unavailable" (not silently ok) → do NOT gate; a `gate=trip` was never overridden to pass.

## Return Contract

Main-thread skill: control returns directly to the caller; the caller decides based on `{workdir}/result.json`. There is no Task-subagent `STATUS:` last-line signal from this skill itself.

Each dispatched per-child sub-Task ends with a harness-level `STATUS: DONE` + a `{"files": [...], "incdirs"?: [...], "annotations": {...}}` JSON line, or `STATUS: BLOCKED <reason>` (schema in `references/child-task-contract.md`).

These signals are consumed by the rtl-design main thread (translated into `fresh_reports.json` for the finalize scripts), not by the caller. The caller only reads this skill's `result.json` envelope (`status ∈ {pass, fail}`).

## Bundled References

- [`references/child-task-contract.md`](references/child-task-contract.md) — the per-child sub-Task prompt + returned annotation schema (dispatched in Step 3).
- [`references/coding-rules.md`](references/coding-rules.md) — RTL coding rules (naming / ports / clocks / resets / FSM / RAM / low-power / datapath).
- [`references/result.schema.json`](references/result.schema.json) — this stage's `result.json` schema.
- [`references/rtl-review-task-contract.md`](references/rtl-review-task-contract.md) — per-child semantic review sub-Task contract (gating; dispatched in Step 4.4).
- [`references/semantic-review.schema.json`](references/semantic-review.schema.json) — schema for the aggregated `semantic-review.json`.
