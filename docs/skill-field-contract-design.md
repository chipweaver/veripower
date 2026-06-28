# `skill-field-contract-design.md` — SKILL.md body contract

## 1. Scope

This document defines the authoring contract for the body of every `skills/<name>/SKILL.md`
file in VeriPower: which fields are required, how each field must be written, and the
formatting conventions that govern the whole body.

**References scope.** Two of these conventions also govern the skill's `references/*.md` files: the
§4.6 formatting conventions (stated there) and the §3.6 voice convention (via its reader-based
extension, stated there). Every other rule in this document is SKILL.md-body-only.

**Audience.** Skill authors writing or revising the body of `skills/<name>/SKILL.md`.

**Companion documents.**

- `skill-frontmatter-design.md` — governs the `name` and `description` frontmatter keys; their
  full rules are out of scope for this document.
- `skill-branch-routing-design.md` — governs Step 1 of the Workflow field in detail: the
  two-signal routing table, branch-coverage rule, and per-form carve-outs.
- `skill-structure-design.md` — governs the orchestration-vocabulary prohibition that constrains
  the content of every field in SKILL.md, and the Bundled References field rule: externalization
  criteria and the suffix naming taxonomy.
- `result-schema-design.md` — covers `result.json` content (what fields belong inside it);
  no overlap with this document, which covers the SKILL.md prose that produces `result.json`.

## 2. Background

A SKILL.md body contains 11 body fields (the full 13-field set includes 2 frontmatter keys).
Those 11 fields carry the operational contract the executing agent follows: when to apply the
skill, what files it reads and writes, how it performs its work, and under what conditions it
returns control. A formal contract prevents drift across all 12 SKILL.md and gives reviewers a
stable audit surface — without it, each skill accumulates local idioms that erode cross-skill
consistency and make automated compliance checks unreliable.

For the relationship between SKILL.md and `result.json`, see `result-schema-design.md`: SKILL.md
describes how to produce the stage artifact; `result-schema-design.md` describes the artifact's
content.

## 3. Foundation principles

### 3.1 F1 — Filesystem is the contract

Cross-stage communication in VeriPower is `result.json` on disk plus the envelope schema —
not free-form prose, not message-body text, not inferred state. The filesystem is what
`state.py` validates, what downstream consumers read at envelope-read time, and what
`promote()` hardlinks to the canonical path.

Implication: every Workflow field must drive toward producing a valid `result.json` on disk.
Status decisions (`pass` or `fail`) must be filesystem-observable — recorded in
`result.json.status`, not inferred from message content. A skill that describes what to
understand rather than what to write fails this principle.

### 3.2 F2 — Four cognitive sections, one axis

Four fields serve distinct cognitive roles; each rule belongs in exactly one. The split turns
on a single axis — severity first, then temptation:

- **Iron Rule** — hard rules the agent must *know*: violation irrecoverably corrupts a
  downstream consumer or breaks stage isolation, and a well-informed agent has no incentive to
  break it (failure mode: ignorance; countermeasure: inform).
- **Red Flags** — hard rules the agent is *tempted* to rationalize past under pressure, even
  when they are also contracts (failure mode: rationalization; countermeasure: steel —
  `Excuse → Reality`).
- **Pitfalls** — recoverable, non-rationalized execution slips, correctable in real time
  (`Mistake → Fix`).
- **Completion Gate** — the pre-return checklist.

A rule is hard xor soft; among hard rules, tempting → Red Flags, else Iron Rule (tie → Red
Flags). Duplicating a rule across sections creates drift anchors — forbidden.

### 3.3 F3 — Process over knowledge

Workflow steps describe *how to do*, not *what to understand*. Each step must be actionable:
it names a concrete action, specifies the condition under which it applies, and identifies the
concrete output. LLM-friendliness sub-rules: use `if X then Y` decisions, action verbs,
concrete file paths — avoid regional shorthand or implicit assumptions that require cultural
context to interpret.

**Bad:** `Step 2: Understand the synthesis tool's output format.`

**Good:** `` Step 2: Run `make synth`; if exit ≠ 0, read `{workdir}/synth.log` for the `Error-` prefix; on found, write `status=fail` with `fail_reason` set to the error line. ``

### 3.4 F4 — Form emerges from function

Four observed forms exist across the 12 SKILL.md: **worker**, **dialogue**, **analyzer**,
**orchestrator**. These are *descriptive classifications* of how skills compose their fields —
they are not pre-imposed templates the author selects. The form of a skill is determined by
what it does; form differences manifest as deltas within specific field rules (§4.3.5, §4.3.6,
§4.3.7, §4.3.11, §4.3.12 cover these deltas; see also §4.5 form-as-structural-diff catalog).
Worker form is the default; all deviations from worker are annotated as form deltas in the
per-field rules.

### 3.5 F5 — English field titles

Field titles are English-only contract; the canonical English form of each field title
appears in §4.1 below.

For workflow vocabulary used inside SKILL.md bodies, the 12 SKILL.md under `skills/`
are the source of truth — read the already-translated bodies and references to discover
the canonical English terms. There is no separate glossary doc; consistency is enforced
by review.

### 3.6 F6 — Voice

Address the executing agent directly and imperatively. For rules, steps, and gates, command —
"Run `make synth`"; "Do not modify `Design/rtl-design/`" — with no hedging: use *must* / *never*,
not *should* / *consider* (Workflow steps follow §3.3 F3). When an actor must be named, name it by
role: "the main thread" / "the orchestrator" for the dispatching self, "the sub-Task" / "the child"
for a dispatched agent. The fan-out stage skills name both sides by role only where the
main-thread vs. sub-Task split is load-bearing — a step where each side acts and the
distinction drives the instruction — because naming each side reads clearer there. Elsewhere,
where a single actor is meant and no such ambiguity exists, address it directly with the
second-person "you", as a single-actor skill does.

This applies to the skill's own **identity, responsibility, scope, and boundary** statements too —
including the **H1 opener** and **Iron Rule**: write them second-person / imperative ("Your sole
responsibility: …", "Write no `result.json`", "Never run EDA tools"), **never** as third-person
self-narration ("This skill is…", "This skill does not…", "It runs…"). Third person is reserved for
actors that are **not** the executing agent: script/tool actors ("`state.py` writes…"); a dispatched
sub-Task or the dispatching self named by role **where the split is load-bearing**; the downstream
pipeline; the **standardized framework-dispatch wording** carried inline by the field contract —
the §4.3.4 black-box bullet **and** the §4.3.7 Fan-out Dispatch Contract bullets (no Level-2,
dispatch-and-wait, no `state.py`, `STATUS: BLOCKED` handling) **and** the load-bearing Load-mode
dispatch anaphora ("It uses the Task tool…"); the T2 "never auto-fixes" routing fact; and references
to a skill **as an artifact** in `description` / `When to Use` / cross-skill mentions
("Use this skill when…"). These carve-outs reflect existing standardized-inline wording, and the
field contract states the fan-out wording is standardized-inline "the same shape as the black-box
bullet."

Name a concept once and reuse the term verbatim (§3.5 F5); no synonyms for the same thing.

**References.** This voice convention also governs `references/*.md` (as the §4.6 formatting
conventions do). In a reference file the "you" is that file's **reader-actor**, attributed by reader:
a `*-task-contract.md` addresses the dispatched **child / sub-Task** it governs; a template addresses
the **producing stage** that fills it; a coding-rules / contract file addresses the **stage agent**
reading its own rules. Third person stays reserved for the same non-reader actors as in SKILL.md —
scripts, the dispatching self or a different sub-Task named by role, an upstream / downstream stage,
and artifact content / provenance. A file that names its own reader-actor in third person (e.g. an
`## Inputs handed to the child` heading whose body addresses that child as "you") is a miss.

## 4. The 13-field contract

### 4.1 Field-set table

13 fields total: 2 frontmatter keys + 11 body fields. MUST = 8, SHOULD = 5.
MUST fields must have content. SHOULD fields may be omitted only if the upgrade trigger does
not apply — not to save space.

| # | Field ID | Tier | Upgrade trigger (raises SHOULD → MUST) |
|---|---|---|---|
| 1 | `name` | MUST | — |
| 2 | `description` | MUST | — |
| 3 | `When to Use` | MUST | — |
| 4 | `Iron Rule` | SHOULD | Skill has an explicit architectural or contractual constraint whose violation breaks downstream consumers |
| 5 | `Input Artifacts` | MUST | — |
| 6 | `Output Artifacts` | MUST | — |
| 7 | `Workflow` | MUST | — |
| 8 | `Decision Rules` | SHOULD | Skill has priority-conflict rules where two valid paths exist and one must win |
| 9 | `Red Flags` | SHOULD | Skill has ≥1 hard rule a well-informed agent is tempted to rationalize past |
| 10 | `Pitfalls` | SHOULD | — |
| 11 | `Completion Gate` | MUST | — |
| 12 | `Return Contract` | MUST | — |
| 13 | `Bundled References` | SHOULD | Skill body contains an externalizeable self-contained unit per `skill-structure-design.md` criteria |

### 4.2 Removal list

The following fields are forbidden — they MUST NOT appear in any SKILL.md:

| Forbidden field | Reason |
|---|---|
| Frontmatter `allowed-tools` | Declarative non-enforced gate; redundant and crowds out `description` visibility |
| `Quick Reference` | Commands belong embedded in Workflow step text; a separate command table duplicates and drifts |
| `Integration` | Upstream/downstream relations are owned by the `design-flow` orchestrator; stage-to-stage data flows through `result.json`, not document cross-links |
| `Suggested Response Structure` / `Reusable Outputs` | Low ROI; overlaps with Output Artifacts table |
| Status-explanation / stage-wrap-up prose paragraphs | Identical across all 12 SKILL.md; promoted to framework-level template (`stage-subagent.md.tpl`); per-skill copy is drift-only overhead |
| Per-stage artifact-summary headings (`Stage Artifacts`, `Minimum Stage Artifacts`, `Deliverable: result.json`, or similar) | Merged into the Output Artifacts table |
| `Prerequisites` | Merged into Input Artifacts |
| Mode-dispatch heading (`Mode Selection` or similar) | Mode dispatch is expressed implicitly through the branch-routing two-signal model (`{rework_trigger}` × disk-prev-artifact); see `skill-branch-routing-design.md` for the full table |

**Note:** The `allowed-tools` rejection is empirically grounded: `veripower:simulation` listed 14 Write tools while `veripower:rtl-design` and `veripower:synthesis` listed none, yet both wrote files freely — confirming the field is non-enforced.

**Note:** For the orchestration-vocabulary prohibition (no DAG position, no stage names as upstream/downstream labels, no dispatcher implementation details in field content), see `skill-structure-design.md`. For cross-skill data access (via canonical paths, not inlined verbatim), see §4.3.5.

### 4.3 Per-field rules

#### 4.3.1 `name`

Frontmatter key — not a body field. Full rules (kebab-case, ≤3 segments, matches skill
directory name) are in `skill-frontmatter-design.md`.

#### 4.3.2 `description`

Frontmatter key — not a body field. Full rules (sentence shape, "Not for" clause, ≤200
characters) are in `skill-frontmatter-design.md`.

#### 4.3.3 When to Use

Structure: 3–5 bullet trigger scenarios. Each bullet names a concrete situation in which an
agent should invoke this skill. A terminal "Not for X" bullet mirrors the `description`
field's "not for" clause, reinforcing it in the body.

#### 4.3.4 Iron Rule

Per the F2 axis (§3.2), a statement qualifies for Iron Rule iff it is **hard and not tempting**;
a hard rule the agent is *tempted* to rationalize past — even when it is also a contract — belongs
in Red Flags (§4.3.9), not here. "Tempting" is judged against observed/plausible failure modes
(e.g. patch-to-pass / gaming), not speculation; when uncertain, default to Red Flags. Framework-level
rules injected by the dispatcher template — or, for main-thread fan-out skills, stated in the
Fan-out Dispatch Contract sub-block (§4.3.7) — do not belong here.

| Candidate rule | Enters Iron Rule? | Criterion |
|---|---|---|
| `veripower:simulation` must not modify `scaffold-specification.json` | Yes | (a) plan is read-only upstream |
| `veripower:simulation-triage` must not write any files | Yes | (b) analysis/repair separation |
| `veripower:specification` must not write `design.md` while `brainstorm.md` is `Status: draft` | Yes | (a) brainstorm-gate protocol |
| Compilation failure retried blindly after a fix | No → Pitfalls | recoverable slip; analyze the log, then re-run |
| `veripower:synthesis` marking pass when a PPA target is missed | No → Red Flags | hard + tempting (gaming) |

**Form delta — dialogue:** dialogue skills may add gate-state preconditions (e.g., the
brainstorm or review artifact must be `Status: approved` before the skill proceeds to the
next phase). **Form delta — analyzer:** emphasizes the read-only invariant explicitly (no
file writes, no `state.py` calls).

**Standardized mandatory bullet (scripts).** Every skill that invokes scripts MUST carry this
exact `Iron Rule` bullet (one canonical wording — the bold label lead-in per §4.6); a skill with
no scripts (e.g. `brainstorm`) omits it:

- **Scripts are black boxes — never Read their source.** Invoke them per this skill's documented command lines (flags via `--help`); on a non-zero exit act on the documented failure protocol (stderr / `FAIL=` token / stdout verdict), not the source. Sole exception: debugging a suspected bug in a script itself.

#### 4.3.5 Input Artifacts

The field lists the four canonical context variables and the external reference inputs the
skill reads. Only variables the skill actually uses are listed.

**Canonical context variable table:**

| Variable | Purpose |
|---|---|
| `{workdir}` | Current run workspace root (contains the run-number path segment `runs/<N>/`); injected by the dispatcher |
| `{module}` | Module name; injected by the dispatcher |
| `{rework_trigger}` | Optional: path to a trigger-context file injected by the caller; contains `stage_specific.violations[]` and related context for the current revision round; its presence is the primary branch-routing signal |
| `{orchestrator_context_path}` | Optional: path to a fix-scope hint file (e.g., triage diagnosis, convergence hint); when present, narrows scope more precisely than `{rework_trigger}.violations[]` alone |

For branch-routing semantics of these variables — how their presence/absence determines
forward vs. rework vs. cascade-rework paths — see `skill-branch-routing-design.md`.

Hard constraints on variables: SKILL.md must never hard-code `asic/<M>`, `asic/<module>`, or
`runs/<N>` path fragments — use `{workdir}` exclusively. `{mode}` is removed from all
SKILL.md files; mode routing is expressed entirely through the variables above. New variables
require a matching injection point in `framework/references/prompts/stage-subagent.md.tpl`
before they can appear in SKILL.md.

**Form delta — analyzer:** Analyzer skills (e.g., `veripower:simulation-triage`) receive
their inputs as inline content embedded in the dispatch prompt, not via `{workdir}` or
`{rework_trigger}`. There is no disk scan. The `{rework_trigger}` × disk-prev-artifact
two-signal routing model does not apply. Source of record:
`skills/simulation-triage/SKILL.md` — *"No `{workdir}` concept; external reference inputs
are supplied entirely as inline content in the dispatch prompt by the caller; no disk
scan."*

#### 4.3.6 Output Artifacts

`result.json` is always the first row of the output table — it is the stage's status contract.
All paths are expressed relative to `{workdir}`; no `asic/<M>` or `runs/<N>` hard-coding.
Table columns: Path (relative to `{workdir}`) / Schema or format / Use. For what belongs
inside `result.json`, see `result-schema-design.md`.

**Form delta — analyzer:** The output table has one row only, rewritten as "ANALYSIS JSON in
the final block of the message body" with schema `references/analysis.schema.json`; no file
is written to disk.

**Form delta — dialogue:** The standard table gains 1–2 additional rows for approval-gated
artifacts (e.g., `brainstorm.md` with frontmatter `Status: approved`, or `verification-plan.md`
after review sign-off).

**Form delta — orchestrator:** The orchestrator skill does not write business artifacts
directly — downstream stages write them. The output table lists only `asic/{module}/task.json`
and `events.jsonl` (maintained by `state.py`), with a note that this skill only triggers
commands.

#### 4.3.7 Workflow

Structure: numbered step **headings** — each top-level step is an H3 heading `### Step N:
<Title>` (colon separator; the em-dash is reserved for *intra-title* clauses, e.g.
`### Step 2: Wave 1 — dispatch env-build`). Numbered markdown lists (`1.` `2.`) are used only
for sub-steps inside a step and other ordered sub-sequences, never for the top-level steps.
Step 1 is a read-inputs step; the worker form's three-branch decision is the default, but
degenerate forms collapse to fewer branches (a stage that never receives `{rework_trigger}`
has no rework branch; the analyzer reads inline input with no disk scan).
See `skill-branch-routing-design.md` for the complete two-signal table and the
branch-coverage = step-coverage rule. Apply the F3 LLM-friendliness sub-rules (§3.3) throughout.

Commands are embedded directly in the relevant step text — no separate Quick Reference table.

**Form delta — dialogue:** Step 1 incorporates disk-reentry detection for the brainstorm or
review state. Example branch: if `brainstorm.md` already exists and is `Status: approved`,
skip the brainstorm phase; if `design.md` already exists, enter the incremental-update branch.
The `external-reference pre-check` and `status=fail` + `fail_reason` semantics apply the same
as in worker form.

**Form delta — analyzer:** Step 1 reads the inline prompt content — there is no disk scan.
The analyzer has **no** `{rework_trigger}` variable; its inputs (the failed-case material) are
inlined directly into the dispatch prompt (consistent with §4.3.5 and the §6.5 carve-out in
`skill-branch-routing-design.md`). Standard worker three-branch logic does not apply.

**Form delta — orchestrator:** Step 1 reads `task.json` dispatch state (the dispatcher
exemption in `skill-structure-design.md` applies; the orchestrator is the dispatcher and is
exempt from the self-containment vocabulary prohibition). The orchestrator is also exempt from
the Step-heading rule: its Workflow is not a linear `Step 1..N` sequence (setup-once + a
repeating executor loop), so it uses descriptive H3 block headings
(`### Setup (once per session)`, `### Executor loop (each turn)`) with no Step numbering.

**Cross-cutting addendum — main-thread fan-out (not a form).** Skills loaded via `Skill()` that dispatch Level-1
sub-Tasks (currently `specification`, `rtl-design`, `simulation`, and `simulation-plan`) include a numbered **Fan-out Dispatch
Contract** sub-block under Workflow stating the framework dispatch rules (no Level 2, dispatch-and-wait,
no `state.py`, sub-Task `STATUS: BLOCKED` handling). Dispatch-and-wait is the
main-thread orchestration lifecycle (the harness wake protocol), enforced at the framework / harness
layer, not by this skill; they sit **outside** the Iron Rule / Red Flags /
Pitfalls severity axis and **outside** the Completion Gate by design.
These framework dispatch rules are carried **standardized-inline**, not via a link to a design doc:
the three per-child-wave skills (`specification`, `rtl-design`, `simulation`) share one canonical
wording (dispatch-and-wait lifecycle, `STATUS: BLOCKED`→`fail` mapping) matching this addendum,
while `simulation-plan` carries a scoped variant for its single-review-dispatch shape (one review
sub-Task; dispatch-and-wait; no `state.py`). Authors apply the wording, reviewers check it (the same
shape as the §4.3.4 black-box bullet).

#### 4.3.8 Decision Rules

This field lists priority-conflict resolution rules only: situations where two valid choices
exist and one must win. It is not branch routing (routing lives in Workflow) and it is not a
boundary constraint (that lives in Iron Rule). Per F2, this is a distinct cognitive section.

#### 4.3.9 Red Flags

Field: Red Flags (SHOULD; upgrade trigger: the skill has ≥1 hard rule a well-informed agent is
tempted to rationalize past). Per F2, this is the *hard + tempting* cognitive section. Structure:
a single `Excuse → Reality` table — the Excuse column is the trigger-thought the agent catches
itself making; the Reality column is the rebuttal. Every row is **hard** by definition (a
recoverable rationalization is a Pitfall, §4.3.10). Omit the section when the skill has none.
Placed immediately before Pitfalls.

**Match the form to the failure.** A Red Flags table fits a *discipline* lapse — the agent knows
the rule but rationalizes past it under pressure. A *wrong-shaped-output* failure (a bloated
dispatch prompt, a malformed `result.json`, a restated spec) is not a rationalization; its
countermeasure is a **positive recipe / contract** — the Fan-out Dispatch Contract, the
`result.json` schema, the wave structure — not a prohibition table. Prohibitions backfire on
shape failures: they enumerate what not to do without showing the shape to produce.

#### 4.3.10 Pitfalls

Structure: a single `Mistake → Fix` table of **recoverable** execution slips — non-rationalized
mistakes the agent corrects in real time. Rows carry no inline severity marker: hard rules live
in Iron Rule / Red Flags and are gate-checked there; Pitfalls holds only the soft set.

#### 4.3.11 Completion Gate

Structure: a pre-return checklist. All items must be satisfied before the skill proceeds to
Return Contract. Per F2, this is the *pre-pass* cognitive section. Standard items:

```markdown
## Completion Gate

- [ ] `{workdir}/result.json` has been written and passes schema validation.
- [ ] Every artifact path is listed in `result.json.artifacts[]`.
- [ ] No Iron Rule or Red Flag was triggered.
- [ ] The `result.json.status` decision has been written (`pass` or `fail`).
```

For non-worker forms, additional or replacement items apply (see §4.5 for the full form-by-field-delta catalog):

- Dialogue: append a user-approval gate (the brainstorm or plan artifact must be in `Status: approved` state before completion).
- Analyzer: replace item 1 with an ANALYSIS JSON validity check (the final block of the message body contains valid JSON per `references/analysis.schema.json`); replace item 2 with a no-files-written invariant (no disk writes, no `state.py` calls).
- Orchestrator: this field does not apply per-turn (no single-turn pre-return semantics); replace entirely with a "main-loop termination conditions" section listing three states: terminate / yield turn / escalate.

#### 4.3.12 Return Contract

Structure: the last line of the skill's response carries an ASCII protocol signal. The
envelope schema (`framework/references/schemas/envelope.schema.json`) accepts exactly two `status`
values: `pass` and `fail`. Both are written to `result.json`; `fail` carries
`stage_specific.fail_reason` with the sub-classification reason.

**Critical:** `STATUS: BLOCKED` is a harness-emitted signal on program exception — the skill
itself never writes it as a logic decision. `pass` and `fail` live in `result.json.status`.
A skill that chooses `STATUS: BLOCKED` to express a workflow decision (e.g., "upstream not
ready") is a contract violation (see also the "BLOCKED uniform removal" architectural invariant).
The envelope schema does not accept `blocked`; the harness emits `STATUS: BLOCKED` only when
`result.json` was not written due to a crash or program exception.

**Standard worker / Task-subagent template:**

```markdown
## Return Contract

As the last line, emit `STATUS: DONE` (when `result.json` has been written) or
`STATUS: BLOCKED <one-line reason>` (when a program exception prevented the write).
The harness uses this signal to fire the Task-completion notification; the caller then
decides based on `result.json`.
```

**Form delta — dialogue:** Dialogue skills are loaded in the main thread; there is no
task-notification mechanism. Replace with: "Control returns directly to the caller; the
caller decides based on `result.json`."

**Form delta — analyzer:** The caller consumes the ANALYSIS JSON block in the message body,
not `result.json`. Replace with:

```markdown
## Return Contract

Return a message whose final block contains valid ANALYSIS JSON (schema:
`references/analysis.schema.json`). On the last line, emit `STATUS: DONE` or
`STATUS: BLOCKED <one-line reason>` as the harness signal.
```

**Form delta — orchestrator:** This field does not apply (main-loop semantics replace
per-turn return contract). Replace with a "main-loop termination" section listing: terminate
/ yield turn / escalate.

#### 4.3.13 Bundled References

Structure: a link list pointing to externalized `references/*.md` or `references/*.json`
files. For the externalization decision criteria (hard conditions, soft signals, carve-outs)
and the suffix naming taxonomy, see `skill-structure-design.md`.

### 4.4 ASCII keyword layers

Two distinct layers of ASCII-preserved keywords exist in VeriPower skills. Localizing any
of these breaks the contract they serve.

| Layer | Tokens | Where it appears | Why ASCII-preserved |
|---|---|---|---|
| End-line protocol | `STATUS: DONE` / `STATUS: BLOCKED <reason>` | Last line of the skill response | Harness parses the literal string; non-ASCII breaks task-notification signal |
| Envelope enum | `pass` / `fail` | `result.json.status` | JSON schema enum; not localized |

**Note:** Scattered English keywords used as prose vocabulary inside a SKILL.md body (MUST,
DO NOT, BLOCK, etc.) are in a different category from the two layers above. They are
ordinary prose and translate naturally to whatever language the skill body is written in.
Only the two ASCII-preserved layers above are protected — the `STATUS:`
end-line protocol and the `pass` / `fail` envelope enum.

### 4.5 Form-as-structural-diff catalog

The four forms (worker / dialogue / analyzer / orchestrator) produce deltas in five specific
fields. This table is a cross-tab summary; for the full rule in each field, see the §4.3.x
subsections cited.

| Form | Input Artifacts delta (§4.3.5) | Output Artifacts delta (§4.3.6) | Workflow delta (§4.3.7) | Completion Gate delta (§4.3.11) | Return Contract delta (§4.3.12) |
|---|---|---|---|---|---|
| worker | Standard `{workdir}` / `{module}` / `{rework_trigger}` / `{orchestrator_context_path}` | `result.json` as first row; additional artifact rows | Three-branch: trigger-driven / cascade-rework / first-run | Standard four-item checklist | `STATUS: DONE` or `STATUS: BLOCKED` on exception |
| dialogue | Same as worker | Append approval-gated artifact rows (e.g., `brainstorm.md` with `Status: approved`) | Step 1 adds disk-reentry detection for brainstorm/review state; same external-ref pre-check | Append user-approval gate item | Replace with direct control-return; no harness signal |
| analyzer | Inputs are inline in dispatch prompt; no `{workdir}`, no disk scan | ANALYSIS JSON block in message body; no file write | Step 1 reads inline prompt content; no two-signal routing | Replace items 1–2: ANALYSIS JSON validity + no-files-written invariant | Return ANALYSIS JSON body + `STATUS: DONE` or `STATUS: BLOCKED` on exception |
| orchestrator | Reads `task.json` dispatch state; dispatcher-exemption applies | Lists `task.json` + `events.jsonl` only; downstream stages write business artifacts | Setup + executor loop, not a Step 1..N sequence; Setup reads `task.json` dispatch state | Not applicable per-turn; replaced by main-loop termination conditions | Not applicable per-turn; replaced by main-loop termination section |

**Note:** Branch-name definitions and full per-field rules live in §4.3.5, §4.3.7, §4.3.11, §4.3.12. The table above is the cross-form summary.

### 4.6 Universal formatting conventions

These conventions apply to every SKILL.md body and every `references/*.md` file:

- Heading hierarchy: H1 (title, one per file) → H2 → H3 → H4. In **SKILL.md**, H2 are the
  canonical **field titles** (`## When to Use`, `## Workflow`, …; never `## 1.`/`## 2.`), and
  Workflow H3 steps use `### Step N: <Title>` (orchestrator exempt — see §4.3.7); descriptive
  non-step H3 sub-blocks are permitted under any field (e.g. `### Fan-out Dispatch Contract`,
  `### Context variables`, `### Session-resume semantics`) — only the sequential Workflow steps
  take `### Step N:`. In the **design docs themselves**, H2/H3 are numbered sections (`## 1.`,
  `### 3.1`, `### 4.3`); H4 only when essential (the §4.3.x per-field rules use H4).
- H1 title content: a concise Title Case **concept name** for what the skill is — one coherent
  concept. The skill's functional identity lives in the frontmatter `name:`/`description:`; the
  H1 is human-facing prose that no tooling, test, or dispatch reads. Do not echo the `name:`
  slug back in parentheses, and do not enumerate the skill's internal steps or outputs.
  Good: `# Power Analysis`, `# Static Timing Analysis`, `# Verification Planning`.
  Bad: `# Verification Planning (simulation-plan)` (slug echo), `# UVM Environment + Compile +
  Smoke + Regression + Coverage Iteration` (step enumeration), `# Frontend Sign-off Checklist`
  (reduces a terminal gate to one of its outputs).
- No `---` horizontal rules between H2 sections.
- Bold: the sanctioned idiom is the **label lead-in** — a Title-Case label opening a load-bearing
  bullet or line (`**Critical:**`, `**Rationale:**`, `**Why:**`, `**Note:**`, `**Dispatch-and-wait:**`,
  … — illustrative, not a closed list) — plus whole-sentence load-bearing rules and defined terms /
  field names. Inline single-word or short-phrase emphasis (`**not**`, `**only**`) is rare: prefer
  rewording over mid-sentence bold. Never XML tags (`<Bad>` / `<Good>`).
- Every fenced code block carries a language tag: `markdown`, `bash`, `json`, `yaml`, etc.
- A runnable script invocation goes in its own ` ```bash ` fenced block, not inline; the prose
  around it describes what the command does and the non-zero-exit protocol. A skill names its
  **own** `scripts/` and `references/` via `${CLAUDE_SKILL_DIR}/…`; the verbose
  `${CLAUDE_PLUGIN_ROOT}/skills/<self>/…` is reserved for cross-skill and framework paths, plus
  artifacts deployed into a workdir (a deployed `templates/` README is read where no skill is
  active, so `${CLAUDE_SKILL_DIR}` does not resolve there).
- Inline backticks for paths, filenames, command / script names and flags, schema field names,
  variable names: `{workdir}`, `result.json`, `STATUS: DONE`.
- In SKILL.md, top-level Workflow steps are `### Step N:` headings (§4.3.7), not a numbered
  list; numbered lists are for sub-steps within a step and other ordered sub-sequences. Bullets
  for unordered observations. Never mix both styles within a single section.
- Good vs. Bad example pairs appear inline immediately after the rule they demonstrate, not in
  a separate examples section.
- Cross-skill references by name (`veripower:<skill-name>`), never by `@`-path.

**Note:** these conventions apply to SKILL.md and `references/*.md` prose. They do not apply
to schema descriptions, Python/Bash/TCL scripts, Makefile targets, or other non-prose
surfaces — those have their own conventions documented elsewhere.

**Note:** §5 (Examples) is intentionally absent. Per-field examples live inline with each
`### 4.3.x` per-field rule rather than in a separate Examples section. Section numbers are
preserved to match the template positions used across the design-doc set.

## 8. Process for changing

**Changing a field tier (MUST ↔ SHOULD):** requires empirical evidence across all 12 SKILL.md
that the trigger consistently applies or consistently does not apply. Speculative upgrades
(e.g., "most skills will need this") are not sufficient. A tier change is a breaking change
for compliance tooling, validated by veripower-review — there is no deterministic test to update.

**Adding a new field:** requires an audit-driven justification (a demonstrated gap in all 12
SKILL.md files that cannot be served by an existing field), consensus on the field's cognitive
role per F2, and an atomic update across all 12 SKILL.md files. Adding a field that only one
or two skills need is a sign the information belongs in those skills' `references/` content
instead.

**Coordination requirements:** if a field change affects `result.json` shape, coordinate with
the relevant `result.schema.json` and bump `schema_version` per `result-schema-design.md §8`.
If the change affects frontmatter fields, run veripower-review to validate — there is no deterministic frontmatter test.
