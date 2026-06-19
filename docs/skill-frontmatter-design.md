# `skill-frontmatter-design.md` — frontmatter design

## 1. Scope

This document governs the 2-key frontmatter contract (`name` and `description`) for every
`skills/<name>/SKILL.md` file in VeriPower.

**Audience.** Skill authors writing or revising `name` and `description`.

**Companion documents.**

- `skill-field-contract-design.md` — body field rules including the F5 English field-title
  convention (frontmatter keys have no Chinese titles and are not in that table).
- `skill-references-organization-design.md` — `references/` directory organization and
  naming.

## 2. Background

Frontmatter is the 2-key contract (`name` + `description`); both are injected into the system
prompt. The `description` is the load-bearing surface for skill discovery: the runtime reads
it to decide which skill loads for a given task.

The English field-title convention for body fields lives in `skill-field-contract-design.md`
§3.5 F5. Frontmatter keys `name` and `description` carry no Chinese titles and are not in
that table.

## 3. Principles

### 3.1 P1 — `name` is kebab-case and matches directory

The `name` value must use lowercase letters, digits, and hyphens only, ≤3 segments
(e.g., `rtl-design`, `simulation-triage`, `lint-cdc`). No plugin namespace prefix — the
value is `rtl-design`, not `veripower:rtl-design`. It must equal the skill's directory name;
the plugin loader uses the directory name to locate the skill.

Names are stage / domain nouns (`rtl-design`, `timing-analysis`), not gerund-first action verbs
(`write-the-design`, `run-synthesis`) — a deliberate genre choice: the name denotes the DAG node /
artifact the skill owns, not a user-invoked action.

### 3.2 P2 — `description` sentence shape

Mandatory pattern: `Use when <trigger>; not for <anti-pattern>.` Single line, ≤200 chars,
third person, "Use when" head.

**Critical:** The "Not for" clause is mandatory. Do not skip it even when the anti-pattern
feels obvious — explicit exclusions prevent skill-load collisions across overlapping skills.

**Bad:** `description: Use when running synthesis.`

**Good:** `description: Use when running Design Compiler synthesis; not for simulation, power-analysis, or timing closure.`

### 3.3 P3 — Description is "when to use", not workflow summary

The `description` is injected into the system prompt and governs skill loading. If it
summarizes the workflow, the agent follows that summary instead of reading the full skill body.

**Bad:** `description: Use when executing plans — dispatches subagent per task with code review between tasks`

**Good:** `description: Use when executing implementation plans with independent tasks in the current session`

**Rationale:** Testing confirmed that the bad form causes the agent to follow the description
summary (one review) instead of the skill body (two reviews). The description shortcut
overrides the body.

### 3.4 P4 — CSO keyword coverage

The description must contain searchable domain terms, tool names, and symptom phrases.
Keyword density drives discovery when Claude matches description text against task context.

Aim for 2+ domain-specific keywords (e.g., `RTL`, `Verilog`, `SDC`, `SGDC`, `lint`,
`synthesis`, `UVM`, `SAIF`). Generic descriptions cannot be reliably retrieved from the
description-discovered pool.

**Genre note — VeriPower dispatch is deterministic.** The 9 pipeline stages are dispatched by
`orchestrate.py`, not retrieved by description-matching, so P3/P4's discovery pressure binds
only for the description-discovered skills (`brainstorm`, `design-flow`, `simulation-triage`).
For the orchestrate-dispatched stages, treat P3 (no workflow summary) and P4 (keyword coverage)
as scope-clarity + human-readability discipline, not as load-bearing for dispatch.

### 3.5 P5 — Frontmatter language is strictly English

No Chinese characters in `name` or `description`. Domain-specific terms (`RTL`, `SDC`, `SGDC`,
`UVM`, `design.md`) appear in English or acronym form.

**Rationale:** Skill discovery is English-keyword-indexed. Injecting Chinese into the discovery
context degrades retrieval precision for all English-language task inputs.

## 4. Rules, checks, and examples

### 4.1 Pre-commit 5-question check

1. Is the `description` third person?
2. Does it follow `Use when <trigger>; not for <anti-pattern>.`?
3. Is it ≤200 chars?
4. Does it contain 2+ searchable keywords (error tokens, symptoms, tool names)?
5. Does it avoid summarizing the workflow?

### 4.2 Annotated real samples

**`specification` (188 chars):**

*"Use when writing or reviewing design specification (design.md), defining interfaces or constraints (SDC/SGDC), or updating from rework feedback; not for RTL implementation or verification."*

- Keywords: `design.md`, `SDC`, `SGDC`, `RTL`, `rework` (5 keywords)
- Anti-pattern: explicit cross-stage exclusions (RTL implementation, verification)

**`rtl-design` (183 chars):**

*"Use when writing or modifying Verilog/SystemVerilog RTL, maintaining filelist, or recording top module + constraint annotations in README.md; not for verification, lint, or synthesis."*

- Keywords: `Verilog`, `SystemVerilog`, `RTL`, `filelist`, `lint`, `synthesis` (6 keywords)
- Anti-pattern: three downstream stage exclusions

**`simulation-triage` (161 chars):**

*"Use when simulation stage fails and root cause analysis is needed before rework decision; not for fixing code, modifying state, or running regression. Read-only."*

- Keywords: `simulation`, `root cause`, `rework`, `regression` (4 keywords)
- Anti-pattern: three action exclusions; `Read-only.` suffix signals the analyzer form

### 4.3 Forbidden patterns

- First-person voice (`I can help with...`)
- Workflow summary in description (`Use when X — does A, then B, then C`)
- Missing "Not for" clause
- `allowed-tools` frontmatter key (see `skill-field-contract-design.md` §4.2 removal list)
- Plugin-namespace prefix in `name` value (`name: veripower:rtl-design` — wrong; use
  `name: rtl-design`)

**Note:** Sections 5 and 6 of the adaptive section template (Examples, What does NOT belong) are absorbed into the rules above; this doc has no separate Examples or NOT-belong sections. The §7 and §8 numbering is preserved to match the universal-section positions used across the design-doc set.

## 7. Compliance checklist

- [ ] `name` is kebab-case, ≤3 segments, matches skill directory name
- [ ] `description` follows `Use when …; not for …` sentence shape
- [ ] `description` is ≤200 chars
- [ ] `description` is third person
- [ ] `description` contains 2+ searchable keywords
- [ ] No `allowed-tools` or other forbidden frontmatter keys present

## 8. Process for changing

When refining a description, keep the sentence shape and tune keyword density — do not add
workflow steps. When the "Not for" clause changes, audit sibling skills for scope collisions:
narrowing an exclusion can create overlap with an adjacent skill's trigger.

Validation: frontmatter is reviewed by `veripower-review` (C2-07 frontmatter); there is no deterministic frontmatter test.
