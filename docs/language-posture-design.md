# `language-posture-design.md` — Bilingual Invariant

## 1. Scope

This document defines the **Bilingual Invariant** — the rule that governs
which content in VeriPower is English-only and which is bilingual. It is
read by skill authors when writing or translating skills, references,
design docs, or framework code.

**Audience.** Skill authors; framework maintainers; reviewers.

**Companion documents.**

- `skill-structure-design.md` — skill and reference organization;
  a separate concern from language posture.

## 2. Background

VeriPower serves both Chinese and English users — as designers using the
tool and as contributors writing skills. The Invariant draws the boundary:
content the LLM
consumes at runtime is English; content that flows between the agent and
the user follows the user's language.

## 3. Surface 1 — runtime-LLM-consumed content (English)

Content that the skill dispatcher, the executing agent, or the eval
harness loads into the agent's context window at runtime is **Surface 1**
and is strict English.

Exemplars: `skills/<name>/SKILL.md` (frontmatter + body);
`skills/<name>/references/*.md` (when linked from SKILL.md).

**Note — matcher pattern data.** A Surface-1 script may carry Surface-2
literal tokens as *matcher pattern data* when its job is to detect
user-language content. Such tokens are matched data, not authored
Surface-1 prose; the script's own agent-facing output stays English.

## 4. Surface 2 — user-data interfaces (bilingual)

Content that is free-prose, flows between the agent and the user, or is
read/written by the agent as a data value inside an artifact or message
body is **Surface 2** and follows user language. It is not parsed as
fields by any matcher.

Exemplar: live agent↔user dialogue; runtime artifact prose in
`brainstorm.md` body cells and `design.md` cell content.

## 5. The two-stage test

For any content, determine its tier with two questions:

**Stage 1 — runtime vs. offline:**

> "Does any dispatcher, harness, or executing agent load this file into
> the agent's context window during a skill or eval run?"

- Yes → continue to Stage 2.
- No → project documentation; language follows the audience; not a Surface (see §7).

**Stage 2 — parsed vs. content (only for runtime-loaded files):**

> "Is this content parsed as a data field, referenced by name, validated
> by schema, or used as an input to a matcher?"

- Yes → Surface 1 (English).
- No → Surface 2 (user language; free-prose content in a structural
  slot).

## 6. Anchor example

**Surface 1 example:**

```markdown
## When to Use

- Write or revise the design.md spec.
- Not for: RTL implementation, verification, or synthesis.
```

At runtime, dialogue follows the language the user has been writing in.

## 7. Not a Surface — project documentation

Project documentation is read by humans offline. Its language follows its
audience; the runtime language convention
applies to skill instructions and artifacts.

**Committed bilingual mirrors.** A few human-facing docs carry a committed
`.zh.md` mirror for Chinese readers (such as `ARCHITECTURE.zh.md` and `USER-MANUAL.zh.md`).
A mirror is a translation of its English source,
not an independent document: the English source is authoritative and the
mirror MUST be updated in the same change as that source, to keep their facts aligned.
