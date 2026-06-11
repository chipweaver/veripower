# `language-posture-design.md` — Bilingual Invariant

## 1. Scope

This document defines the **Bilingual Invariant** — the rule that governs
which content in VeriPower is English-only and which is bilingual. It is
read by skill authors when writing or translating skills, references,
design docs, or framework code. It is **not** loaded into Claude's
context at runtime; no SKILL.md references this file.

**Audience.** Skill authors; framework maintainers; reviewers.

**Companion documents.**

- `skill-self-containment-design.md` — orchestration-vocabulary scrub;
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

Examples of Surface 1:

- `skills/<name>/SKILL.md` (frontmatter + body).
- `skills/<name>/references/*.md` (when linked from SKILL.md).
- `skills/<name>/scripts/*` (executed at runtime; stdout/stderr read by
  Claude).
- `skills/<name>/templates/*` (structural skeleton; field labels;
  placeholders).
- `skills/<name>/defaults.yaml`.
- `framework/scripts/state.py` (executed; orchestration authority).
- `framework/references/prompts/stage-subagent.md.tpl` (injected on
  every subagent dispatch).
- `framework/references/schemas/*.schema.json` (validation contract;
  descriptions read on error).
- The project root `CLAUDE.md` (loaded by Claude Code at session start).
- `tests/unit/*.py` (assertion strings define the contract surface).
- `tests/scenarios/<stage>/scenario-*.md` frontmatter keys (parsed by
  the eval framework).

## 4. Surface 2 — user-data interfaces (bilingual)

Content that is free-prose, flows between Claude and the user, or is
read/written by Claude as a data value inside an artifact or message
body is **Surface 2** and follows user language. It is not parsed as
fields by any matcher.

Examples of Surface 2:

- Live Claude↔user dialogue.
- Runtime artifact prose: `brainstorm.md` body cells, `design.md` cell
  content, `verification-plan.md` text.
- `result.json.stage_specific.fail_reason` runtime values.
- Simulated user-utterance text in
  `tests/scenarios/<stage>/scenario-*.md` body and frontmatter values.

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

## 6. Examples

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

**Bad — forcing Surface 2 to English when the user works in another
language.** A dialogue skill that prompts the user in English when the
user has been writing in (say) Chinese creates friction and may confuse
the user. Surface 2 is meant to follow the user, not impose a language.

**Good — Surface 2 mirrors user language.** The dialogue skill's
SKILL.md is English (Surface 1 — authoring content); at runtime Claude
emits the prompt in whatever language the user has been writing in.
This is emergent behavior: Claude's pretrained language-mirroring is
sufficient; no explicit instruction in any SKILL.md is needed.

**Bad — mandating one language for `fail_reason` runtime values.** The
spec does not pin a language for `fail_reason` values. Forcing English
when the surrounding dialogue is non-English makes the failure narrative
read awkwardly. Forcing user-language when the failure is a
cross-stage protocol observation makes it less greppable.

**Good — `fail_reason` reflects runtime context.** The value emerges
from the runtime narrative; if the dialogue is non-English, the value
may be non-English. The SKILL.md examples illustrating `fail_reason`
syntax stay English (Surface 1 — authoring content).

## 7. Not a Surface — project documentation

Project documentation — `docs/*.md`, `CONTRIBUTING.md`, root `README.md`,
`ARCHITECTURE.md`, `framework/README.md`, `templates/<stage>/README.md`,
and code comments throughout — is read by humans offline. It is English
by general standardization policy for consistency and contributor
friendliness, but it is not part of the LLM runtime contract and does
not fall under the Bilingual Invariant.

## 8. Enforcement posture

- **No SKILL.md cross-references this principle or any file in `docs/`.**
  Skills are self-contained.
- **Authors learn the rule from this doc** when writing or translating
  skills; reviewers verify on PR.
- **Claude relies on emergent language-mirroring** at runtime — no
  explicit "speak the user's language" instruction in any SKILL.md.
- **The forbidden-keyword grep** in `skill-self-containment-design.md §4`
  is the only mechanical enforcement for skill content, and it catches
  orchestration vocabulary, not language.
