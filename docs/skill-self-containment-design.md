# `skill-self-containment-design.md` — orchestration-vocabulary scrub

## 1. Scope

This document governs the orchestration-vocabulary scrub rule for all files under
`skills/<name>/`: `SKILL.md`, `references/*.md`, `scripts/*`, `templates/*`, schema
`description` fields, and code comments. Audience: skill authors writing or modifying any
part of a stage skill directory.

Companion: `skill-branch-routing-design.md` §6 covers protocol-identifier semantics for
`{rework_trigger}` and `{orchestrator_context_path}`.

## 2. Background

VeriPower's DAG topology and dispatch logic are owned exclusively by `design-flow`.
Individual stage skills, in contrast, describe a bounded operation: what they receive, what
they produce, and what they decide internally. They do not describe DAG position, who calls
them, or how their failures are routed. DAG-agnostic descriptions stay composable and
replaceable — topology can evolve without touching stage content.

## 3. Principles

### 3.1 P1 — Describe self, not orchestration

A stage skill describes what *this skill* does, its inputs, its outputs, and its internal
decision rules. It does NOT describe who calls it, when dispatched, what happens to its
outputs, or how failures are routed. Any sentence mentioning DAG structure, stage
relationships, or dispatch mechanics is a P1 violation.

### 3.2 P2 — Recursive scope

The self-containment rule applies recursively to the entire `skills/<name>/` tree.
`SKILL.md` compliance alone is insufficient. In scope: `references/*.md`, `scripts/*`
comments, `templates/*` prose, `defaults.yaml`, Makefile comments, and JSON schema
`description` fields. One section's compliance does not excuse a violation elsewhere.

### 3.3 P3 — Carve-outs are scoped to identifiers, not blanket

Filename and variable-name occurrences of §4 keywords are exempt at the identifier level
(see the §4 note); the surrounding descriptive prose still must follow the scrub rule.
The §6 catalog enumerates the dispatcher exemption with decision rules. Keywords outside a
carve-out context are scrubbed or rewritten per §5.

## 4. Forbidden keyword catalog

**Pipeline-position vocabulary** — describes DAG or dispatch mechanics; forbidden:
`DAG`, `cascade rework`, `convergence`, `Orchestrator`, `design-flow`,
`main-thread skill`, `Stage subagent`, `Task dispatch`, `dispatcher`,
`ESCALATE`, `handle_failure`.

**State-machine / orchestration-layer identifiers** — `state.py`, `events.jsonl`, `task.json`, `orchestrate.py`, `route.py`, `topology.py` name
orchestration-layer internals. Stage skills write `result.json` and return; they do not
reference the state-machine layer by name.

**Sibling-stage narrative references** — referring to a stage as "the downstream consumer"
or "the upstream source" is forbidden. Describe data flow by canonical artifact paths, not
by named stages.

```bash
# Forbidden orchestration vocabulary (use as a grep pattern):
DAG|Orchestrator|design-flow|cascade rework|state\.py|events\.jsonl|task\.json|orchestrate\.py|route\.py|topology\.py|ESCALATE|handle_failure|convergence|dispatcher|main-thread skill|Stage subagent|Task dispatch
```

**Note — protocol-identifier carve-out.** Filename and variable-name occurrences of these
keywords are exempt at the identifier level (e.g., `{rework_trigger}`,
`{orchestrator_context_path}`, `orchestrator-context.md`, `events.jsonl`, `task.json`).
The forbidden-keyword rule constrains *descriptive prose* around these identifiers, not
their literal use as protocol tokens. The `simulation-triage` `root_cause` enum literals
(`rtl-design`, `simulation-plan`, `specification`, `simulation`) are also identifier-level
— they name a repair target, not a narrative DAG-position claim.

## 5. Bad / Good rewrite table

| ✗ Bad (violation) | ✓ Good (rewrite) | Violation type |
|---|---|---|
| *"This skill is the canonical input source for all downstream stages."* | *"This skill's sole responsibility: collapse X into a frozen Y artifact."* | Pipeline position |
| *"This skill is the DAG root; on failure, the orchestrator escalates directly."* | *(delete the sentence; how failure is handled is not this skill's concern)* | DAG + orchestrator + routing |
| *"The orchestrator reads `result.json.status` and calls `state.py reap`."* | *"On completion, write `result.json` and return."* | Orchestrator implementation |
| `{rework_trigger}` *"points at the downstream stage's `result.json` that triggered this run"* | `{rework_trigger}` *"caller-injected context-file path; contains `violations[]`"* | DAG language in variable description |
| `### Upstream Artifacts` (heading) | `### External reference inputs` (heading) | Structural DAG vocabulary |

## 6. Carve-outs

### 6.1 Dispatcher exemption

Two kinds of skill carry orchestration vocabulary *in-role*, so it is their subject
matter rather than a violation:

1. **Router** — `design-flow`. Its output *is* a routing decision; DAG / orchestrator /
   routing vocabulary is what the skill is about.
2. **Fan-out dispatchers** — `specification`, `rtl-design`, `simulation`, and `simulation-plan`
   (scoped). These are main-thread skills that hold Level-1 sub-Task dispatch authority
   (ARCHITECTURE §6.3.1): `specification` runs two sub-Task waves around its partition
   gate (decompose + per-child), `rtl-design` runs one per-child fan-out wave,
   `simulation` runs two sequential waves around its smoke gate (env-build → smoke gate
   → verify), and `simulation-plan` self-dispatches a single Level-1 plan-adequacy review
   sub-Task at its adequacy gate (one scoped review dispatch, not a per-child fan-out).
   Because dispatching and reaping their own Level-1 sub-Tasks *is* their
   control flow, `dispatcher` / `orchestrate` / `sub-Task` / `wave` / `Task` vocabulary in
   their `SKILL.md` describes the skill's own operation, not a sibling stage or the DAG.
   The `No state.py` self-restriction these skills state is likewise in-role (it scopes
   their own dispatch authority), not a sibling-orchestration narrative.

**Decision criterion:** the vocabulary describes *this skill's own operation* — emitting a
routing decision (router) or driving its own intra-stage fan-out (fan-out dispatcher) →
exempt. The vocabulary describes who calls the skill, what happens to its outputs, or how
its failures are routed → working-stage narrative → §4 applies, even inside a fan-out
dispatcher. Producing a domain artifact (design.md, RTL, reports) does NOT by itself forfeit
the carve-out: a fan-out dispatcher both fans out sub-Tasks *and* finalizes an artifact, and
the dispatch vocabulary that drives the fan-out stays exempt.

The exempt set is closed: `design-flow` + the four fan-out dispatchers above. A new
dispatcher (router or fan-out) must be explicitly added here, with the §8 atomic discipline,
before the exemption applies to it.

**Bad / Good (a fan-out dispatcher's own SKILL.md):**

| ✗ Bad (violation — sibling/DAG narrative) | ✓ Good (in-role — own fan-out control flow) |
|---|---|
| *"The orchestrator dispatches this stage, then routes its `result.json` to the downstream consumer."* | *"This skill dispatches one Level-1 sub-Task per child, reaps each, then writes `result.json`."* |
| *"The review sub-Task writes no `task.json`, appends no events, and does not count against the orchestrator's in-flight bound (§6.3.1 of ARCHITECTURE.md)."* | *"This skill dispatches one Level-1 review sub-Task, reaps it, and folds the result."* |

## 7. Compliance checklist

- [ ] No P1 violations in `SKILL.md` (manual review against §4 + §5 table)
- [ ] No P2 violations elsewhere in the skill tree (`references/`, `scripts/`, `templates/`,
  schema descriptions, comments)
- [ ] Run forbidden-keyword grep across the skill directory:
  ```bash
  grep -rn -E 'DAG|Orchestrator|design-flow|cascade rework|state\.py|events\.jsonl|task\.json|orchestrate\.py|route\.py|topology\.py|ESCALATE|handle_failure|convergence|dispatcher|main-thread skill|Stage subagent|Task dispatch' skills/<name>/
  ```
  Filter results through the §4 protocol-identifier carve-out and the §6.1 dispatcher
  exemption before treating any hit as a violation.
- [ ] Every remaining hit resolves to the §4 protocol-identifier carve-out (filename or
  variable-name occurrence), OR is rewritten per §5
- [ ] If the skill is `design-flow` (router) or one of the fan-out dispatchers
  (`specification`, `rtl-design`, `simulation`, `simulation-plan`), the §6.1 exemption covers vocabulary that
  describes its own routing / intra-stage fan-out; only sibling-stage or DAG-position
  narrative (who calls it, what consumes its outputs, how failures route) still counts as a
  violation

## 8. Process for changing

**Extending §4:** propose in a spec, grep the candidate pattern across all 12 SKILL.md,
classify each hit as true-violation or carve-out, and update affected skills atomically in
the same commit.

**Adding a new carve-out** (e.g., a new identifier-level exemption to extend the §4 note,
or a new dispatcher exemption): same atomic discipline. Include a concrete rationale and at
least one inline Bad/Good example pair; carve-outs without examples are insufficient.
