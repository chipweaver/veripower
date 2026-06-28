---
name: veripower-review
description: Use when reviewing your own VeriPower change (a commit or working-tree diff) or a named part of the current VeriPower codebase against VeriPower's own accumulated design discipline; advisory and read-only. Not for reviewing a user's chip design and not a pipeline stage.
disable-model-invocation: true
---

# VeriPower Quality Review

Review a target — a change (Mode 1) or current code (Mode 2) — for real quality, read through
VeriPower's own design principles. **Advisory and read-only:** produce findings + a report; never
modify code, state, or git.

**Falsify, don't endorse.** Treat the change as a hypothesis to break, not a conclusion to confirm —
the current state, the convention it follows, and your own first read are all hypotheses. This
adversarial stance is your recall now that there is no multi-pass: a single honest pass that *tries
to find what is wrong* beats three passes that look for reasons it is fine. For anything you judge,
ask two questions: **is it correct? and even if correct, is it the best form?** — and apply both to
the change *and* to the convention it follows. Verify a claim at its source; do not inherit it, and
do not let local success stand in for global correctness.

Your job is **judgment, not conformance-matching.** The principles in §3 are lenses that sharpen what
you look for — not a checklist to tick, and "departs from a past convention" is not a finding when the
departure is genuinely better (say so, at most as a `consider`). The mechanical invariants — schema
validity, state write-order, eligibility recheck, artifact-path containment, determinism strata — are
already enforced in code/test/schema and fail loud at runtime; do not re-audit those code-caught
invariants here (the few that have no runtime backstop are lenses in §3). Spend your attention on
what code cannot catch: real bugs, bad abstractions, omissions, and the durable principles below.

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
- a producer ↔ its consumers (the script or stage-package verb that emits an artifact ↔ whatever
  reads it downstream);
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
  a required field then continuing; a shell producer without `set -euo pipefail`.
- **Single canonical home** — Is each rule/datum stated once with one owner, or duplicated across
  sites that will drift? *Shape:* the same rule copied into two docs; a value re-stated inline
  instead of referenced; a cross-referencing doc or rule that will drift from what it points at.
- **Skill authoring** — In a SKILL.md change, does each field and step do its one job, in
  process form (action + condition + output, not knowledge) and imperative voice? *Shape:* a rule
  duplicated across cognitive sections (a drift anchor); knowledge-prose where an actionable step
  belongs; third-person self-narration where "you" belongs; `should` / `consider` hedging where a
  rule means `must` / `never`.
- **Same-change guard** — Does a change that adds a structured thing ship its guard in the same
  change? *Shape:* a new `result.json` / event field with no validation test; a new advisory artifact
  with no validator its producer runs before emitting; a new DAG stage missing from a `topology.py`
  map, its scenario tests, or the orchestrator update.
- **Invariant residue (no runtime backstop)** — Does the change hold the two invariants code cannot
  sandbox — stage isolation and scripted verdict gates? *Shape:* a `Task()` inside a Task-dispatched
  stage's sub-Task, or the dispatcher full-file-Reading such a stage's SKILL.md to inline it; a
  mechanical pass/fail verdict the SKILL.md tells the model to eyeball from a slack / error number
  instead of a unit-tested parser computing it.
- **Claims backed** — Is every factual claim the change makes (commit message, comment, doc) backed
  by ground truth? *Shape:* a "shared" / "all consumers" claim with no real citer; a cited
  file:line / symbol / anchor that does not resolve; a count the diff contradicts; a "done / tests
  pass" claim with no command output or test; a "saves N%" optimization with no baseline.

## 4. Quality on the merits

This is the main work: judge the change on its merits — is it correct, well-designed, complete —
**not** by whether some doc named the issue.

- Is it correct? Is there a real bug, an unhandled edge, a race, a wrong result? Read the actual
  logic — not just the shape.
- Does this abstraction deserve to exist? Does the change solve the real problem, or the wrong one?
- What's missing? An omission — a producer updated with its consumer left behind, a claim with no
  backing, a counterpart left stale (this is why §2 pulls them in), a blind spot the lenses don't name.
- **Is the convention itself best-in-class?** A change can faithfully conform to a convention that is
  itself wrong. Evidence is input, not a mandate: a rule, a repeated pattern, or a count does not
  make the thing right. Ask the second question — minimal? single canonical home? process over
  knowledge? form follows function? the right form for its failure mode? — and flag a convention that
  has stopped earning its place, not only a change that breaks one. This is the dimension a
  conformance check structurally cannot see.

## 5. Write findings

Emit one finding per issue, ordered must-fix → should-fix → consider:

`[<severity>] <file:line> — <evidence> — <concrete fix>`

- Separate responsibility: mark each finding **objective** (a clear defect), **judgment** (a call the
  author could reasonably differ on), or **owner-decision** (surface it with a recommendation; do not
  decide it silently). A quality tradeoff with no clear right answer is at most `consider`.
- Prefer the minimal sufficient fix: solve by deleting, collapsing, or standardizing in place before
  adding any new file, rule, field, or layer — do not cure bloat with more structure.

End with a one-line verdict that **names the files you covered**, so an incomplete pass is visible.
Write findings + verdict as markdown to
`${CLAUDE_PROJECT_DIR}/docs/superpowers/reviews/<YYYY-MM-DD>-<target-slug>.md` (`mkdir -p` first;
`<target-slug>` = `worktree` / `HEAD` / `staged` / a short commit-or-branch slug / the Mode-2 path
with `/`→`-`). This area is gitignored — the report is not committed.

## Boundaries

- Read-only: never edit code; never touch `task.json` / `events.jsonl` / git state.
- Advisory: findings inform; they block nothing. Keep this judgment-heavy review on-demand,
  never wired in as a standing pass/fail gate.
- One pass, but a complete one: cover every changed surface, not a sample. Run no multi-pass recall
  machinery — depth comes from the falsify stance and reading the actual logic once, thoroughly, not
  from re-running the review.
- Never read `~/.claude` memory — it is not a repo-authoritative source.
