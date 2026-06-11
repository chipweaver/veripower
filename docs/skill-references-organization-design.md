# `skill-references-organization-design.md` — references/ design

## 1. Scope

This document governs the externalization decision for skill authors: what content belongs in the
`SKILL.md` body, what belongs in `skills/<name>/references/*.md` (skill-private), and what belongs
in `framework/references/*.md` (cross-skill shared). Audience: anyone writing or auditing a stage
skill directory. Companion: `skill-field-contract-design.md` §4.3.12 (Bundled References field rule).

## 2. Background

VeriPower uses a three-layer content model:

1. **SKILL.md body** — entry point; inline-friendly content the agent reads in a single context load.
2. **`skills/<name>/references/`** — skill-private externalizations; specific to one stage.
3. **`framework/references/`** — cross-skill shared pool; centralized to prevent N-copy drift.

The canonical English title `Bundled References` is owned by
`skill-field-contract-design.md` §4.1; per-field rules live in §4.3.12 of that doc.

## 3. Principles

### 3.1 P1 — Single canonical home

Every rule has exactly one canonical home; cross-references use markdown links, never duplication.
Maps to review framework B7 and C5. *N copies = N drift anchors.*

### 3.2 P2 — Hard criteria plus soft signals

Externalize when a hard criterion is met (see §4). Soft signals (concept orthogonality, evolution
cadence difference) are reviewer hints only — authors do not externalize on soft signals alone.

### 3.3 P3 — One-layer `references/`

`references/` is a flat directory: no nested subdirectories. Private references
(`skills/<name>/references/`) must not cross-reference other skills' private references; only
`framework/references/` is shareable across skills.

### 3.4 P4 — Filename conventions

Markdown, schema, and shell files use kebab-case. Python files follow PEP 8 snake_case (import
constraint). Six naming-suffix patterns, applied in order (use first match):

- `*.schema.json` — machine contract
- `*-template.md` — reusable prose template
- `*-rules.md` — rule set
- `*-checklist.md` — check list
- `*-patterns.md` — taxonomy or playbook
- `<topic>.md` — fallback

## 4. Externalization decision cascade

Apply steps in order; stop at the first match.

1. **Hard criteria check (any one match → externalize):**
   - Machine contract: program-consumed structured data (e.g., `result.schema.json`,
     `envelope.schema.json`).
   - Cross-skill shared: consumers in different skills; not externalizing forces N drift copies.
   - Fits a §3.4 six-suffix type AND is ≥ 30 lines (self-contained; readable without surrounding
     SKILL.md context).

2. **If no hard criterion matched, check soft signals (reviewer-only):**
   - Concept orthogonal to the surrounding workflow context.
   - Evolution cadence differs from the skill body.
   - Length smell: SKILL.md body > 250 lines — signal to re-examine, not a mandate.

3. **Default: keep inline.**

Six-suffix taxonomy:

| Suffix pattern | Type | Examples |
|---|---|---|
| `*.schema.json` | machine contract | `result.schema.json`, `analysis.schema.json` |
| `*-template.md` | reusable template | (none currently — placeholder for future) |
| `*-rules.md` | rule set | `coding-rules.md`, `uvm-rules.md` |
| `*-checklist.md` | check list | (placeholder) |
| `*-patterns.md` | taxonomy / playbook | (placeholder) |
| `<topic>.md` | fallback | `coverage-iteration.md`, `repair-boundaries.md` |

## 5. Two examples

**Example 1 — externalize:** `skills/rtl-design/references/coding-rules.md` — RTL coding
conventions, 131 lines. Hard criterion met: `*-rules.md` suffix + ≥ 30 lines; self-contained
without surrounding Workflow context. **Action:** externalize; list in Bundled References.

**Example 2 — keep inline:** A hypothetical 25-line "decision tree for picking simulator memory
model". Soft signal hit (concept orthogonal to surrounding workflow) but fails all hard criteria:
not a machine contract, not cross-skill shared, below 30 lines. **Action:** keep inline.

## 6. Inline-only content, cross-skill ref syntax, and authoritative artifacts

### 6.1 Inline-only content

The following are always kept in the SKILL.md body. All are stage-bound; externalizing adds
navigation cost without separability benefit.

- **Workflow** — agent reads steps in sequence during execution; external loading breaks single-context.
- **Pitfalls** — mid-flow warnings needed in context during Workflow execution.
- **Completion Gate** — pre-return checklist; co-located with Return Contract.
- **Return Contract** — terminal action; inseparable from Completion Gate.
- **Decision Rules** — local priority-conflict rules scoped within this stage.
- **When to Use** — dispatcher reads this at invocation time.
- **Iron Rule** — architectural boundary constraints; must be visible before step 1.
- **Input/Output Artifacts tables** — stage-specific I/O; orphans if externalized.

### 6.2 Cross-skill reference syntax

Reference other skills by name with the `veripower:` namespace prefix. Never use `@`-path includes
or file-path cross-links that force-load another skill's context.

**Good:** *"For verification-plan authoring, see veripower:simulation-plan."*

**Bad:** *"For verification-plan authoring, see `@skills/simulation-plan/SKILL.md`."*

**Bad:** *"Read `skills/simulation-plan/SKILL.md` first, then return here."* (sequence dependency)

**Note:** Markdown links within a doc are fine — e.g.,
`[F5 mapping](skill-field-contract-design.md#35-f5--bilingual-field-title-mapping-canonical-home)` —
they are navigation aids that do not force-load context.

### 6.3 Authoritative artifacts to consult before drafting

Consult these ground-truth sources before drafting (review framework B1 sidebar):

- `framework/scripts/state.py` — `PREREQ_OF`, `SKILL_OF`, `_RESULT_DIR`: stage ordering and result layout.
- `framework/references/schemas/envelope.schema.json` — envelope fields; `status ∈ {pass, fail}` (`blocked` invalid).
- `skills/<name>/references/result.schema.json` — per-stage `stage_specific` shape.
- `skills/design-flow/SKILL.md` — dispatcher expectations and failure routing.
- `docs/result-schema-design.md` — three-role framing (R1 completion certificate / R2 artifact manifest /
  R3 structured handoff); four-question test for `stage_specific` fields.
- `ARCHITECTURE.md` — DAG topology, state-machine semantics, canonical-vs-`runs/` layout.

## 7. Compliance checklist

- [ ] Externalization decisions follow §4 hard criteria (not soft signals alone)
- [ ] `references/` has no nested subdirectories
- [ ] Private references do not cross-reference other skills' private `references/` files
- [ ] Filenames follow kebab-case + Python snake_case + six-suffix conventions from §3.4
- [ ] SKILL.md body ≤ 250 lines (smell threshold; not a hard limit)
- [ ] Cross-skill references use `veripower:<name>` syntax, not `@`-path or file-path includes

## 8. Process for changing

**Promoting inline content to a `references/` file:** the content must satisfy at least one §4
hard criterion. Once moved, update the `Bundled References` field in SKILL.md to list the new file.

**Promoting private content to shared:** move from `skills/<name>/references/` to
`framework/references/`; update every skill that referenced the private copy. Stale private copies
re-create the N-drift problem the promotion was meant to solve.
