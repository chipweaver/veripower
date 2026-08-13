# `language-posture-design.md` — Bilingual Invariant

## 1. Scope

This document defines the **Bilingual Invariant** — the rule that governs
which content in VeriPower is English-only and which is bilingual. It is
read by skill authors when writing or translating skills, references,
design docs, or framework code. It is **not** loaded into Claude's
context at runtime; no SKILL.md references this file.

**Audience.** Skill authors; framework maintainers; reviewers.

**Companion documents.**

- `skill-structure-design.md` — orchestration-vocabulary scrub;
  a separate concern from language posture.

## 2. Background

VeriPower serves both Chinese and English users — as designers using the
tool and as contributors writing skills. A naïve "everything in English"
rule conflicts with the bilingual user posture; a naïve "everything
bilingual" rule degrades LLM skill-execution quality because the
runtime-loaded content drifts away from the form Claude reasons best
about. The Invariant draws the boundary precisely: content the LLM
consumes at runtime is English; content that flows between Claude and
the user follows the user's language.

## 3. Surface 1 — runtime-LLM-consumed content (English)

Content that the skill dispatcher, the executing agent, or the eval
harness loads into Claude's context window at runtime is **Surface 1**
and is strict English. This is the highest-leverage content in the
repo — every token directly affects model behavior.

Exemplars: `skills/<name>/SKILL.md` (frontmatter + body);
`skills/<name>/references/*.md` (when linked from SKILL.md).

**Note — matcher pattern data.** A Surface-1 script may carry Surface-2
literal tokens as *matcher pattern data* when its job is to detect
user-language content. Such tokens are matched data, not authored
Surface-1 prose; the script's own Claude-facing output stays English.

## 4. Surface 2 — user-data interfaces (bilingual)

Content that is free-prose, flows between Claude and the user, or is
read/written by Claude as a data value inside an artifact or message
body is **Surface 2** and follows user language. It is not parsed as
fields by any matcher.

Exemplar: live Claude↔user dialogue; runtime artifact prose in
`brainstorm.md` body cells and `design.md` cell content.

## 5. The two-stage test

For any content, determine its tier with two questions:

**Stage 1 — runtime vs. offline:**

> "Does any dispatcher, harness, or executing agent load this file into
> Claude's context window during a skill or eval run?"

- Yes → continue to Stage 2.
- No → project documentation; English by policy, not a Surface (see §7).

**Stage 2 — parsed vs. content (only for runtime-loaded files):**

> "Is this content parsed as a data field, referenced by name, validated
> by schema, or used as an input to a matcher?"

- Yes → Surface 1 (English).
- No → Surface 2 (user language; free-prose content in a structural
  slot).

## 6. Anchor example

**Bad — Surface 1 written in any language other than English.** A
SKILL.md body with non-English H2 titles and non-English bullet content
was the pre-rollout state across VeriPower. Surface 1 is now strict
English; the standardization flipped all such surfaces.

**Good — Surface 1 written as English:**

```markdown
## When to Use

- Write or revise the design.md spec.
- Not for: RTL implementation, verification, or synthesis.
```

At runtime Claude emits dialogue in whatever language the user has been
writing in. This is emergent behavior from pretrained language-mirroring;
no explicit "speak the user's language" instruction in any SKILL.md is
needed.

## 7. Not a Surface — project documentation

Project documentation is read by humans offline. It is English by general
standardization policy but is not part of the LLM runtime contract and
does not fall under the Bilingual Invariant.

**Committed bilingual mirrors.** A few human-facing docs carry a committed
`.zh.md` mirror for Chinese readers (currently `ARCHITECTURE.zh.md`).
A mirror is a translation of its English source,
not an independent document: the English source is authoritative and the
mirror MUST be updated in the same change as that source, so the two never
diverge on a load-bearing fact.
