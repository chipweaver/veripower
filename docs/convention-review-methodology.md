# `convention-review-methodology.md` — Re-examining VeriPower's Own Design Discipline

How to step back and judge whether VeriPower's **own** conventions are best-in-class, and where its
docs or implementation can be improved. This is the durable *method*, decoupled from any single run
(§6).

It is advisory and manual: like `veripower-review` it gates nothing, and is run deliberately — when a
benchmark shifts, a new skill or subsystem lands, or a convention starts to feel contingent or
over-grown — not on a cadence.

## 1. The two layers it operates on

- **Layer 1 — the design docs themselves.** The conventions and the docs that own them: the Tier-A
  doc set checked by `veripower-review`'s **C2-15** — `docs/*-design.md`, `ARCHITECTURE.md`,
  `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`. A doc's `.zh` translation is a **propagation target**,
  not a member of that set.
  - **1a — soundness:** internally consistent, not stale, doc matches code.
  - **1b — quality:** is each convention best-in-class — minimal, self-standing, the right form?
    *This is the dimension `veripower-review` cannot check: no rubric item judges whether a convention
    is itself well-formed, only whether a change conforms to it.*
- **Layer 2 — implementation follows the docs** (`skills/`, `framework/`, schemas conform).

Settle Layer 1 before judging Layer-2 conformance — don't measure implementation against a ruler that
is itself wrong.

## 2. The flow

### Phase 1 — Reconcile to reality (Layer-1a hygiene + Layer-2 conformance)

Run `veripower-review` on the target (Mode-2 named path, or its §5 fan-out for a large target) for the
hygiene and conformance checks it owns. Then read for **doc↔code drift** its fixed checks miss: for
each convention the docs state, find the code that implements it and confirm the description still
matches.

A drift *class* the review structurally misses is a **rubric gap**: file it as a candidate rubric
entry, keeping the single canonical home in the rubric (C2-06). This method adds no second checker —
its only original work is Phase 2.

### Phase 2 — Layer-1b quality (the dimension this method exists for)

Judge the reconciled conventions against the quality lens (§3) with an **adversarial fan-out**:
dispatch independent reviewers, scaled to target size, each prompted to **refute** against §3 and the
convention's owning doc, cross-checking docs-vs-reality and docs-vs-criteria. Self-review
rationalizes; independent refutation catches more.

### Phase 3 — Impact-tag each proposal

Each proposal carries its propagation impact, so applying it is *complete* — no lagging sibling left
behind:

- **Consistency fan-out** — every sibling site that must state the convention identically. This
  includes a doc's `.zh` mirror (e.g. `ARCHITECTURE.md` → `ARCHITECTURE.zh.md`), though that
  obligation has no canonical home yet — treat it as a Phase-1 candidate gap, not a settled rule.
- **Conformance fan-out** — every implementation spot that must follow the convention.

Because the method is propose-only, the consistency work rides on each proposal as its impact rather
than a separate sweep — one idea, one name.

## 3. The Layer-1b quality lens

Apply the rules that already own these properties — as questions, do not re-derive them:

- minimal, earns its place (**C1-04**);
- single canonical home, stated once (**C2-06**);
- process over knowledge (**F3**); form follows function (**F4**);
- self-contained and complete, with the right form for its failure mode.

For **SKILL.md-authoring** conventions, the lens is the design's own **F1–F6**
(`docs/skill-field-contract-design.md` §3), scoped to skill authoring. For everything else (state,
schemas, topology, routing), apply the questions above against the `docs/*-design.md` that owns the
convention.

## 4. External comparison (optional input)

Pointed at an external reference library, the method may treat divergences as candidate gaps: a
**genre-justified** divergence (VeriPower's context warrants it) is kept; an unjustified one becomes a
proposal.

The library is a **process input only**. The report (§6, gitignored, not Tier-A) **may** name it as a
finding's rationale; but a proposal **applied to a shipped doc** must re-express its rationale on
first-principles terms — per C2-15, no external name or path enters a Tier-A doc.

## 5. Action boundary

**Read-only / propose-only.** The method diagnoses and proposes; it never edits, commits, or touches
`task.json` / `events.jsonl` / git. The operator applies, commits per theme, and syncs the rubric /
memory.

## 6. Output, and the method vs. a run of it

This doc is the **instance-free method** and is never edited to record findings. A *run* produces
dated artifacts under the gitignored `docs/superpowers/` — a decisions log (`specs/<YYYY-MM-DD>-…`)
and the report (`reviews/<YYYY-MM-DD>-<target-slug>.md`) — so the next pass reads this doc clean and
re-runs the flow.

The report is a severity-ordered set of proposals (`must-fix` / `should-fix` / `consider`), each
marked **objective** (clear) or **judgment** (operator decides) and carrying its Phase-3 impact tags.
A run is **done** when every in-scope convention has a verdict; it ends with an advisory verdict line.
