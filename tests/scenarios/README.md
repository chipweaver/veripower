# Scenario tests — skill discipline under pressure

Each scenario tests whether a skill's agent makes the right call under pressure (deadline,
authority, sunk cost, …) on an invariant that skill is supposed to enforce. The test **subject** is a
fresh, isolated `claude -p` subprocess run by **`scenario-run.sh`** on **Opus** (the production
model); the verdict is the subprocess's own self-report tag (closed-form) or human / main-agent
judgment (`open`).

**The full procedure lives in [`CONTRIBUTING.md`](../../CONTRIBUTING.md) → "Bulletproofing a skill
(RED-GREEN-REFACTOR)".** This file documents only the corpus layout and conventions.

> **Status (2026-06-10): deliberately lean — exactly 1 teeth-ful scenario.** A full RED-first
> traversal of ~50 candidate invariants across all 12 skills (clean harness, Opus, with a 5× majority
> vote on boundary cases) found that **CLAUDE.md + Opus + EDA domain knowledge already produce the
> compliant behavior for nearly every invariant** — they pass RED, so they're toothless and were not
> kept. The one survivor is `design-flow/scenario-02-escalate-verbatim` (an arbitrary "forward the
> subagent's text verbatim, don't tidy it" convention an over-helpful agent reliably violates under a
> safety-framed prompt: 4/5 RED fail, 0/5 GREEN fail). Methodology note: single-probe RED is noisy —
> the boundary cases need sharpening + a 5× majority vote to separate real teeth from sampling noise.
> An empty per-skill dir is the honest outcome for that skill, not unfinished work.
>
> **(2026-06-18 — baseline change.)** RED no longer injects `CLAUDE.md`; it is now bare Opus (see
> below). The toothlessness verdicts above were taken against the **old CLAUDE.md-inclusive RED**, so
> some "toothless" invariants may bite under the bare baseline — the corpus may legitimately grow.

## Why a subprocess, not an in-session subagent

A RED baseline must be an agent that genuinely lacks the skill's guidance. An in-session subagent
does **not** qualify: it inherits the project `CLAUDE.md`, **the developer's auto-memory, and
repo file-access**, all of which pre-encode the invariants under test (verified 2026-06-10 — a
tools-off subagent still complied, citing the auto-memory's "no skill-decided BLOCKED" note). A
fresh `claude -p` from a temp workdir with `--allowedTools ""` loads no developer auto-memory, no skill, and
can read no repo file — only the context the runner injects. That is the only faithful baseline.

## How a scenario is run

```bash
./tests/scenarios/scenario-run.sh --skill <name> --scenario <id> --mode red     # bare: no project CLAUDE.md, no SKILL.md
./tests/scenarios/scenario-run.sh --skill <name> --scenario <id> --mode green    # + skills/<name>/SKILL.md (SKILL.md alone)
```

1. **RED** (`--mode red`) injects **nothing** — no project `CLAUDE.md`, no `SKILL.md` (bare Opus).
   The agent should *fail* (pick the violating option). A scenario that passes RED is toothless —
   discard or re-aim it at what `SKILL.md` adds.
2. **GREEN** (`--mode green`) injects `SKILL.md` **alone** — exactly what a plugin end-user receives
   (they run VeriPower from outside this repo and never load its `CLAUDE.md`). The agent should
   *comply*. On failure, REFACTOR the skill (from the verbatim rationalization) and meta-test, then
   re-run (see CONTRIBUTING.md).

3. **Record** the provenance stamp (below). The runner prints the self-report tag + the raw
   transcript; it does **no** keyword/regex scoring — you judge.

> **Isolation caveat (A2) — this section is the authoritative baseline description.** `claude -p`
> still auto-discovers the developer's user-level `~/.claude/CLAUDE.md` into both modes. The clean
> fix `claude --bare` is not used: it forces `ANTHROPIC_API_KEY`/apiKeyHelper auth the team lacks.
> Verdicts are therefore only as clean as the runner's `~/.claude/CLAUDE.md`; run with a
> minimal/empty global. `CONTRIBUTING.md` and `tests/README.md` cross-ref this description.

## Scenario types

| Type | Tag the agent self-reports | Verdict |
|---|---|---|
| `pressure` | `DECISION: A/B/C` (first line) | tag vs `expected_choice` (deterministic) |
| `missing-info` | `ACTION: PROCEED/BLOCKED` (first line) | tag vs expected (deterministic) |
| `open` | none | human / main-agent judgment + meta-test (answer key in `## Expected Behavior` / `## Anti-Pattern`) |

`pressure` + `missing-info` are the regression-replayable subset (re-run `--mode green` after editing
a skill; a previously-passing scenario that now fails means the edit reopened a hole). `open` is
judgment-only.

Scenario bodies are bilingual: Chinese narrative + an English pressure-injection block (project
Surface-2 user-data posture). The answer-key sections (`## Expected Behavior` / `## Anti-Pattern`)
are truncated out of the injected prompt by the runner — never part of what the agent sees.

## Provenance stamps

Every closed-form scenario that has been activated carries, in its frontmatter:

```yaml
baseline: fail      # the RED run failed (the scenario has teeth)
green: pass         # the GREEN run passed (the skill holds)
activated: <date>   # when the loop was run
model: opus         # the model used for both runs (= production)
```

The durable evidence of *why* a skill's Red-Flag exists is the rationalization-table row in that
`skills/<skill>/SKILL.md`, derived from the observed verbatim excuse — not the raw transcript.

## Directory layout

```
scenarios/
├── scenario-run.sh            # the clean-isolation runner (one scenario, one mode)
├── templates/                 # scenario authoring templates
│   ├── scenario-template-pressure.md
│   ├── scenario-template-missing.md
│   └── scenario-template-open.md
├── results/                   # raw subprocess transcripts + inventories — gitignored (regenerable)
├── <skill>/                   # one dir per skill; scenario-*.md files
│   └── scenario-*.md
└── README.md
```

## Writing new scenarios

Copy a template under `templates/`, fill in the frontmatter (`skill`, `scenario_id`, `title`, `type`,
plus `expected_choice` for `pressure`), and target what the skill's **`SKILL.md` must carry on its
own** (its mechanisms, exact gates, thresholds) — the production end-user has the `SKILL.md` but not
veripower's `CLAUDE.md`. Then run it through the RED-first acceptance gate (CONTRIBUTING.md) before
committing. A skill whose discipline **bare Opus already holds unaided** legitimately gets few or
zero scenarios.
