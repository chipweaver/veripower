# `skill-frontmatter-design.md` — frontmatter design

## 1. Scope

This document governs the 2-key frontmatter contract (`name` and `description`) for every
`skills/<name>/SKILL.md` file in VeriPower.

**Audience.** Skill authors writing or revising `name` and `description`.

**Companion documents.**

- `skill-field-contract-design.md` — body field rules including the F5 English field-title
  convention (frontmatter keys have no Chinese titles and are not in that table).
- `skill-structure-design.md` — `references/` directory organization and naming.

## 2. Background

Frontmatter is the 2-key contract (`name` + `description`); both are injected into the system
prompt. The `description` is the load-bearing surface for skill discovery: the runtime reads
it to decide which skill loads for a given task.

The English field-title convention for body fields lives in `skill-field-contract-design.md`
§3.5 F5. Frontmatter keys `name` and `description` carry no Chinese titles and are not in
that table.

## 3. Principles

### 3.1 P1 — `name` is kebab-case and matches directory

Names are stage / domain nouns (`rtl-design`, `timing-analysis`), not gerund-first action verbs
(`write-the-design`, `run-synthesis`) — a deliberate genre choice: the name denotes the DAG node /
artifact the skill owns, not a user-invoked action. The plugin loader uses the directory name to
locate the skill, so the `name` value must equal the directory name.

### 3.2 P2 — `description` sentence shape

Mandatory pattern: `Use when <trigger>; not for <anti-pattern>.` Single line, ≤200 chars,
third person, "Use when" head.

**Critical:** The "Not for" clause is mandatory. Do not skip it even when the anti-pattern
feels obvious — explicit exclusions prevent skill-load collisions across overlapping skills.
Without it, the dispatcher has no boundary to arbitrate when two skill descriptions both match
the task context.

**Bad:** `description: Use when running synthesis.`

**Good:** `description: Use when running Design Compiler synthesis; not for simulation, power-analysis, or timing closure.`

### 3.3 P3 — Description is "when to use", not workflow summary

The `description` is injected into the system prompt and governs skill loading. If it
summarizes the workflow, the agent follows that summary instead of reading the full skill body.

**Bad:** `description: Use when executing plans — dispatches subagent per task with code review between tasks`

**Good:** `description: Use when executing implementation plans with independent tasks in the current session`

**Rationale:** Testing confirmed that the bad form causes the agent to follow the description
summary (one review) instead of the skill body (two reviews). The description shortcut
overrides the body. This is the strongest evidence-backed principle in this document.

**Genre caveat — VeriPower dispatch is mostly deterministic.** The 9 pipeline stages —
plus `simulation-triage`, itself a kernel Task rule — are dispatched by `kernel.py decide`,
not retrieved by description-matching, so the discovery pressure in P3 binds primarily for
the description-discovered skills (`brainstorm`, `design-flow`). For kernel-dispatched
stages, treat P3 (no workflow summary) as scope-clarity and human-readability discipline.

Frontmatter must be English. See `language-posture-design.md` §3 (Surface 1) for the
canonical rationale.

## 8. Process for changing

When refining a description, keep the sentence shape and tune keyword density — do not add
workflow steps. When the "Not for" clause changes, audit sibling skills for scope collisions:
narrowing an exclusion can create overlap with an adjacent skill's trigger.

Validation: frontmatter is reviewed by `veripower-review`; there is no deterministic frontmatter test.
