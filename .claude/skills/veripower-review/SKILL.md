---
name: veripower-review
description: Use when reviewing your own VeriPower change (a commit or working-tree diff) or a named part of the current VeriPower codebase against VeriPower's own accumulated design discipline; advisory and read-only. Not for reviewing a user's chip design and not a pipeline stage.
---

# VeriPower Conformance Review

Review a target — a change (Mode 1) or current code (Mode 2) — against VeriPower's own
distilled design discipline. **Advisory and read-only:** produce findings + a report; never
modify code, state, or git.

## Knowledge tiers

- **Tier A (live, authoritative)** — read fresh from the repo at review time:
  `${CLAUDE_PROJECT_DIR}/ARCHITECTURE.md`, `${CLAUDE_PROJECT_DIR}/CLAUDE.md`,
  `${CLAUDE_PROJECT_DIR}/CONTRIBUTING.md`, `${CLAUDE_PROJECT_DIR}/README.md`,
  `${CLAUDE_PROJECT_DIR}/docs/*-design.md`.
- **Tier B (the rubric)** — `${CLAUDE_SKILL_DIR}/references/rubric.md`: distilled checkable
  entries. It never restates Tier-A prose; entries point to Tier A via their `ssot` field.

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
- a renamed or removed symbol ↔ its citers (`grep -rn <symbol> "${CLAUDE_PROJECT_DIR}"`).

## 3. Select rubric entries

1. Build the path list: the diff/file set from §1 plus the counterparts from §2. (For Mode 1,
   obtain the file list with `git -C "${CLAUDE_PROJECT_DIR}" diff --name-only <target>`; §1's
   full diff content is for the §4 examination step.)
2. Map each path to `applies-to` tag(s):
   - `*/SKILL.md` → `skill-md`
   - `*/references/*` → `references`
   - `*/scripts/*` or any `*.py` under `skills/` → `scripts`
   - `framework/scripts/*.py` (`state`/`topology`/`orchestrate`/`route`/`artifacts`) → `py-core`
   - `*.md` under `docs/` or the repo root → `docs`
   - any `*result*.json` or `*.schema.json` → `result-schema`
   - `*.sdc` / `*.sgdc` → `constraints`
   - every path → also `any`
3. Select every rubric entry whose `applies-to` intersects the path list's tags.
4. For each selected entry that has a non-dash `ssot`: **verify the anchor still resolves** —
   `grep -nF "<cited anchor text>" "${CLAUDE_PROJECT_DIR}/<cited file>"` (an `ssot` may cite a
   heading or a bold-paragraph title). If it does NOT resolve, emit a `consider` finding against
   the rubric itself (`stale ssot: <id> cites <anchor>`) and recover the rule by scanning the
   file's headings and bold titles
   (`grep -nE '^#{1,4} |^\*\*' "${CLAUDE_PROJECT_DIR}/<cited file>"`) to find where it moved.
   Either way, read only the cited (or relocated) section — not the whole doc, not an unbounded sweep.

## 4. Examine and emit findings

Inspect the target against each selected check. Emit one finding per violation, formatted:

`[<severity>] <id> — <file:line> — <evidence> — <concrete fix>`

Order findings must-fix → should-fix → consider. End with a one-line advisory verdict, e.g.
`verdict: 2 must-fix, 3 should-fix, 1 consider — advisory only, blocks nothing`.

Write the same findings + verdict as markdown to
`${CLAUDE_PROJECT_DIR}/docs/superpowers/reviews/<YYYY-MM-DD>-<target-slug>.md`
(`mkdir -p` the directory first). `<target-slug>` is `worktree`, `HEAD`, `staged`, a short
commit/branch slug, or the Mode-2 path with `/`→`-`. This area is gitignored — the report is
not committed.

## 5. Large Mode-2 audits (optional fan-out)

If the target is repo-wide or `skills/`-wide, dispatch one Task subagent per subsystem; each
runs §1–§4 on its slice and returns findings; then merge. **Mode 1 never fans out.**

## Boundaries

- Read-only: never edit code; never touch `task.json` / `events.jsonl` / git state.
- Advisory: findings inform; they block nothing.
- Never read `~/.claude` memory — the rubric already distilled it once at build time.
