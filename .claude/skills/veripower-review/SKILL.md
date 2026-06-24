---
name: veripower-review
description: Use when reviewing your own VeriPower change (a commit or working-tree diff) or a named part of the current VeriPower codebase against VeriPower's own accumulated design discipline; advisory and read-only. Not for reviewing a user's chip design and not a pipeline stage.
disable-model-invocation: true
---

# VeriPower Conformance Review

Review a target — a change (Mode 1) or current code (Mode 2) — against VeriPower's own
design discipline. **Advisory and read-only:** produce findings + a report; never
modify code, state, or git.

## Knowledge tiers

- **Tier A (live, authoritative — the review's scope)** — read fresh from the repo at review
  time: `${CLAUDE_PROJECT_DIR}/ARCHITECTURE.md`, `${CLAUDE_PROJECT_DIR}/CLAUDE.md`,
  `${CLAUDE_PROJECT_DIR}/CONTRIBUTING.md`, `${CLAUDE_PROJECT_DIR}/README.md`,
  `${CLAUDE_PROJECT_DIR}/docs/*-design.md`. A change is judged against the **design intent in
  Tier A** — that intent, not the rubric, is the scope of the review.
- **Tier B (the rubric, a field guide)** — `${CLAUDE_SKILL_DIR}/references/rubric.md`: a guide to
  what known violations *look like* in the wild. Its job is **specificity** — it sharpens the
  reading so a violation is recognized on sight. It is **not** the boundary of the review (coverage
  comes from the Tier-A worklist in §3) and **not** a checklist to run: an un-distilled rule with no
  entry is still in scope, caught by reading Tier A directly.

## 1. Resolve the target

**Mode 1 (diff)** — a single change:
- No argument + dirty working tree → review uncommitted changes:
  `git -C "${CLAUDE_PROJECT_DIR}" diff HEAD`.
- No argument + clean tree → review the last commit:
  `git -C "${CLAUDE_PROJECT_DIR}" show HEAD`.
- Argument given: a SHA or range `A..B` → `git -C "${CLAUDE_PROJECT_DIR}" diff A..B`;
  `staged` → `git -C "${CLAUDE_PROJECT_DIR}" diff --staged`; a branch name →
  `git -C "${CLAUDE_PROJECT_DIR}" diff main...<branch>`.

**Mode 2 (current-state)** — a named path / subsystem / skill (REQUIRED; there is no
whole-repo default):
- File set = the tracked files under the named path
  (`git -C "${CLAUDE_PROJECT_DIR}" ls-files -- <path>`).
- A repo-wide or `skills/`-wide target is allowed but large → use the fan-out in §5.

## 2. Pull in counterparts

For each file in the target, add its known counterparts to the review set so cross-file and
*omission* violations are reachable (not structurally invisible):
- a `result.json` ↔ its `result.schema.json` (and vice versa);
- a producer script ↔ its consumers (a `derive_*.py` / `*.sh` and the `bootstrap_*.sh` or
  SKILL.md that invokes it);
- a renamed or removed symbol ↔ its citers (`grep -rn <symbol> "${CLAUDE_PROJECT_DIR}"`);
- an English source doc ↔ its committed `.zh.md` mirror (`ARCHITECTURE.md` ↔ `ARCHITECTURE.zh.md`,
  `GETTING-STARTED.md` ↔ `GETTING-STARTED.zh.md`), so a stale / contradicting translation is reachable.

## 3. Build the worklist — surfaces × governing sections

Produce an **explicit worklist** before judging — it is the enumeration that makes recall honest:
the walk follows a written-down list, not free associations, so a skipped item is visible.

1. **Surfaces.** The §1 file set + the §2 counterparts. (Mode 1: get the names with
   `git -C "${CLAUDE_PROJECT_DIR}" diff --name-only <target>`; §1's full diff content is for §4.)
2. **Tag each path:**
   - `*/SKILL.md` → `skill-md`
   - `*/references/*` → `references`
   - `*/scripts/*` or any `*.py` under `skills/` → `scripts`
   - `framework/scripts/*.py` → `py-core`
   - `*.md` under `docs/` or the repo root → `docs`
   - any `*result*.json` or `*.schema.json` → `result-schema`
   - `*.sdc` / `*.sgdc` → `constraints`
   - every path → also `any`
3. **Governing sections — two discovery modes.** List Tier A
   (`ls "${CLAUDE_PROJECT_DIR}"/docs/*-design.md` + the four root docs). A doc enters the worklist
   only for the tags it governs; pull in only its governing sections — not the whole doc.
   - **Scoped design docs** (`docs/*-design.md`) — read each doc's **first section** (under its first
     `##` heading; it declares scope — heading wording varies). A doc governs a touched surface when
     that scope covers the surface's tag; then collect the sections that bear on the surface
     (`grep -nE '^#{2,4} ' <doc>` to enumerate them). A design doc that scopes itself to pipeline
     stage skills under `skills/<name>/` does **not** govern the field / `### Step N:` /
     `## N.`-vs-field-title **structure** of a `.claude/skills/` meta-tooling target (e.g. this
     skill) — for those, only language-posture (C2-08) and content hygiene (C2-04) apply to runtime
     content.
   - **Topic-addressed references** (`ARCHITECTURE.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `README.md`)
     — no single scope statement; governance is per §-topic, mapped by a heading scan
     (`grep -nE '^#{2,4} ' <doc>`). `ARCHITECTURE.md` governs `py-core` / `result-schema` / skill
     dispatch (system model, determinism strata, state model, orchestration loop, subagent/failure/
     dispatch contracts, resume/promote) — so a `skill-md`-only change does **not** pull it in.
     `CONTRIBUTING.md` governs change-obligations across `skill-md` / `py-core` / `result-schema`;
     `CLAUDE.md` and `README.md` govern `any` at the project level.
4. The worklist is the set of `(surface, governing section)` pairs from step 3. For each pair, note
   the Tier-B field-guide entries whose `applies-to` matches the surface and whose `ssot` points into
   that section — those are the violation shapes to keep in mind while reading it in §4.

## 4. Walk the worklist — read source, sharpened by the field guide

Walk **every** worklist pair and record a one-line verdict for each — `violate` / `clean` / `n/a` —
so a skipped pair is never silent. For each pair, read the governing section's actual intent and the
change, and judge whether the change violates that intent. Consult the Tier-B field guide for the
shapes a violation takes (so a known form is caught on sight), but read for the **full intent**,
not only the distilled shapes: a violation with no field-guide entry is a real finding *and* a
field-guide gap — record both. Enumerate within a pair too: treat every instance as a candidate,
never stop at the first. When a rubric `ssot`'s cited anchor does not resolve, emit a `consider`
(`stale ssot: <id> cites <anchor>`) and recover the rule by scanning the file's headings
(`grep -nE '^#{1,4} |^\*\*' <file>`); read the relocated section.

Emit one finding per violation:

`[<severity>] <id-or-"gap"> — <file:line> — <evidence> — <concrete fix>`

Order must-fix → should-fix → consider; end with a one-line verdict, then a **coverage ledger**: the
worklist pairs walked (each with its verdict), any surface or claim **not** covered, every
field-guide gap (a real finding with no entry — feeds the rubric per
`convention-review-methodology.md` Phase 1), and **the passes run and whether they converged** (per
§5 — a single un-converged pass is a visible shortcut, like a skipped pair). The ledger keeps recall
honest: a clean verdict means "clean against the worklist I walked, at the diligence the ledger
records," and the ledger is that record.

Write findings + verdict + ledger as markdown to
`${CLAUDE_PROJECT_DIR}/docs/superpowers/reviews/<YYYY-MM-DD>-<target-slug>.md` (`mkdir -p` first).
`<target-slug>` is `worktree` / `HEAD` / `staged` / a short commit-or-branch slug / the Mode-2 path
with `/`→`-`. This area is gitignored — the report is not committed.

## 5. Multi-pass — union, refute, converge

A single pass finds a real but *random subset*: two independent passes of this skill on one diff
return overlapping-but-different findings, and their union is larger than either. Recall comes from
**multiple independent passes unioned**, not from one careful pass — so multi-pass is the primary
mode, not a high-stakes add-on.

- **Independent passes.** Run the §3–§4 walk at least twice as *independent* passes. The second pass
  is a Task subagent (fresh context = real independence) prompted to assume the change is
  non-conforming and to find what the first pass missed; a larger target warrants more. **Union**
  their findings — disjoint findings are breadth, not error.
- **Refute.** Sweep the union with a pass prompted to **refute** each finding; drop the ones that do
  not survive (kills false positives — `convention-review-methodology.md §2`: independent refutation
  catches more). For a high-blast-radius change (touches `py-core`, a `*.schema.json`, the
  orchestration boundary, or a Tier-A design doc), run the refute pass as its own independent subagent.
- **Converge.** If a pass adds new findings or leaves worklist pairs unwalked, run another. "Clean"
  means the passes **converged** (a pass added nothing new), not that one pass finished.
- **Size fan-out (Mode 2, large target).** Repo-wide or `skills/`-wide → also dispatch one Task
  subagent per subsystem; each runs §1–§4 on its slice; merge, then union + refute as above.

## Boundaries

- Read-only: never edit code; never touch `task.json` / `events.jsonl` / git state.
- Advisory: findings inform; they block nothing.
- The rubric is a field guide, not the boundary — Tier A is the scope (§3 worklist). A clean walk
  that left a worklist pair unread is not a clean review; the ledger says so.
- Never read `~/.claude` memory — it is not a repo-authoritative source; Tier A is.
