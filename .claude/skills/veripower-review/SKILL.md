---
name: veripower-review
description: Use when reviewing your own VeriPower change (a commit or working-tree diff) or a named part of the current VeriPower codebase against VeriPower's own accumulated design discipline; advisory and read-only. Not for reviewing a user's chip design and not a pipeline stage.
disable-model-invocation: true
---

# VeriPower Quality Review

Review a target — a change (Mode 1) or current code (Mode 2) — for real quality, read through
VeriPower's own design principles. **Advisory and read-only:** produce findings + a report; never
modify code, state, or git.

Your job is **judgment, not conformance-matching.** The principles in §3 are lenses that sharpen what
you look for — not a checklist to tick, and "departs from a past convention" is not a finding when the
departure is genuinely better (say so, at most as a `consider`). The mechanical invariants — schema
validity, state write-order, eligibility recheck, artifact-path containment, determinism strata — are
already enforced in code/test/schema and fail loud at runtime; do not re-audit them here. Spend your
attention on what code cannot catch: real bugs, bad abstractions, omissions, and the durable
principles below.

**Cover the whole target, not a sample.** Apply §3 and §4 to *every* changed file and hunk (Mode 1)
or *every* file in the set (Mode 2). A review that inspects a few hunks and stops is a spot-check, not
a review — completeness is the bar for the one pass you run.

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

## 2. Pull in counterparts

For each file in the target, add its known counterparts to the review set so cross-file and
*omission* defects are reachable (not structurally invisible):
- a `result.json` ↔ its `result.schema.json` (and vice versa);
- a producer script ↔ its consumers (a `derive_*.py` / `*.sh` and the `bootstrap_*.sh` or
  SKILL.md that invokes it);
- a renamed or removed symbol ↔ its citers (`grep -rn <symbol> "${CLAUDE_PROJECT_DIR}"`);
- an English source doc ↔ its committed `.zh.md` mirror, so a stale / contradicting translation is
  reachable.

## 3. Judgment lenses

Read the change through these lenses — each is a question plus the shape its violation takes in the
wild. They sharpen recognition; they do not bound the review (a real defect no lens names is still a
finding — see §4). Apply the lenses a surface warrants.

- **Simplicity / no speculation** — Does every changed line trace to the task, or is there an
  abstraction, flag, config, or defensive branch nobody asked for? *Shape:* a new abstraction for
  single use, error-handling for impossible states, unrelated adjacent "improvements."
- **No backward-compat** — Does a fix carry a backward-compat clause or keep a now-dead path "just in
  case"? *Shape:* `(when present)` guards on a now-unconditional contract; defensive legacy
  fallbacks; a dead branch kept rather than deleted with its tests/docs.
- **Audit, don't grandfather** — When overhauling a registry/config, is each existing entry
  re-justified against current evidence? *Shape:* entries kept with no current consumer; "leave it,
  it predates us."
- **No silent transformation** — Does a consumer compose producer data (paths, filelist entries, IDs)
  verbatim, or silently strip/normalize/transform it? *Shape:* `basename` / path-stripping /
  regex-normalization on producer filelist or path-handoff entries.
- **Fail loud** — Does a producer/consumer validate its REQUIRED inputs and abort with a clear error,
  or fall through to a degraded/wrong artifact? *Shape:* a silent `.get(k, "")` / `or []` default on
  a required field; a `bootstrap_*.sh` without `set -euo pipefail`.
- **Single canonical home** — Is each rule/datum stated once with one owner, or duplicated across
  sites that will drift? *Shape:* the same rule copied into two docs; a value re-stated inline
  instead of referenced.
- **Skill authoring (F1–F6)** — for a SKILL.md / skill change: does each field and step do its one
  job, in process form (what to *do* — action + condition + output — not what to understand), in the
  right structural form for what the skill does, in imperative voice? *Shape:* a rule duplicated
  across cognitive sections (a drift anchor); knowledge-prose where an actionable step belongs;
  third-person self-narration where "you" belongs; `should` / `consider` hedging where a rule means
  `must` / `never`.

## 4. Function Y — real quality

This is the main work: judge the change on its merits, **not** by whether some doc named the issue.

- Is it correct? Is there a real bug, an unhandled edge, a race, a wrong result? Read the actual
  logic — not just the shape.
- Does this abstraction deserve to exist? Does the change solve the real problem, or the wrong one?
- What's missing? An omission — a producer updated with its consumer left behind, a claim with no
  backing, a counterpart left stale (this is why §2 pulls them in).
- **Is the convention itself best-in-class?** A change can faithfully conform to a convention that is
  itself wrong — minimal? single canonical home? process over knowledge? form follows function? the
  right form for its failure mode? Flag a convention that has stopped earning its place, not only a
  change that breaks one. This is the dimension a conformance check structurally cannot see.

## 5. Change-discipline + invariant residue

Code/test/schema enforce the mechanical invariants at runtime; a small residue cannot be enforced
there and lives with you. Check these when the change touches their surface.

**Invariant residue (no runtime sandbox catches these):**
- **Stage isolation** — a Task-dispatched stage sub-Task never calls `Task()` itself, and the
  dispatcher never full-file-Reads a Task-dispatched stage's SKILL.md to inline its work; a stage
  moved across the main-thread / Task-dispatched line updates that boundary.
- **Scripted verdict gate** — a pass/fail (or threshold) verdict that is a mechanical function of
  tool-report numbers is computed in a deterministic parser script with a `tests/unit/` test, and
  SKILL.md *runs* the parser; SKILL.md never tells the model to read the report and judge the gate by
  eye. (Genuine-judgment verdicts — failure clustering, semantic intent — are carved out.)

**Change-obligations (a change that adds the thing must add its guard, in the same change):**
- a new routing-verdict field (in `result.json` / an event payload) ships with the schema update AND
  a `tests/unit/test_state.py` coverage test;
- a new descriptive/advisory artifact ships a `scripts/validate_*.py` self-gate the skill runs before
  emitting it;
- a new DAG stage updates all four `topology.py` maps, adds `tests/scenarios/<stage>/`, and updates
  the orchestrator skill if it changes scheduling semantics;
- an English source doc changed in the diff has its committed `.zh.md` mirror updated in the same
  change (a stale or contradicting translation is a defect — pull the mirror in via §2 and diff it).

**Epistemic discipline (judge the change's own claims):**
- every factual claim (commit message, comment, doc) is grep-backed — a "shared" / "all consumers"
  claim has an actual citer, a cited file:line / symbol / anchor resolves, a stated count matches the
  diff;
- a "done / fixed / tests pass / verified" claim carries evidence (the command + its output, a
  failing-then-passing test), not an assertion from intent;
- a claimed optimization isolates its mechanism from confounds — baseline stated, metric measures
  this change, the mechanism shown to actually engage.

## 6. Write findings

Emit one finding per issue, ordered must-fix → should-fix → consider:

`[<severity>] <file:line> — <evidence> — <concrete fix>`

A quality tradeoff with no clear right answer is at most `consider`, never must-fix. End with a
one-line verdict that **names the files you covered**, so an incomplete pass is visible. Write
findings + verdict as markdown to
`${CLAUDE_PROJECT_DIR}/docs/superpowers/reviews/<YYYY-MM-DD>-<target-slug>.md` (`mkdir -p` first;
`<target-slug>` = `worktree` / `HEAD` / `staged` / a short commit-or-branch slug / the Mode-2 path
with `/`→`-`). This area is gitignored — the report is not committed.

## Boundaries

- Read-only: never edit code; never touch `task.json` / `events.jsonl` / git state.
- Advisory: findings inform; they block nothing.
- One pass, but a complete one: cover every changed surface, not a sample. Run no multi-pass recall
  machinery — depth comes from reading the actual logic once, thoroughly, not from re-running the
  review.
- Never read `~/.claude` memory — it is not a repo-authoritative source.
