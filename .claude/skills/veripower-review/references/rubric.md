# VeriPower Review Rubric

Distilled, checkable conformance entries. Built once through an admission gate (currency /
conflict-resolves-to-doc / value / durable-provenance / no-grandfathering). Entries never restate
Tier-A prose; a Tier-A-owned rule carries an `ssot` pointer. Orphan lessons (no Tier-A home)
carry no `ssot` and state their origin plainly in `provenance`.

Each entry:

- **id** — class-numbered handle (`C1-01`, `C2-03`, `C3-02`)
- **check** — the one-line verifiable assertion
- **signal** — how to detect a violation
- **severity** — `must-fix` / `should-fix` / `consider`
- **applies-to** — `any` / `skill-md` / `references` / `scripts` / `py-core` / `docs` / `result-schema` / `constraints`
- **ssot** — Tier-A citation (pointer entries only; `—` for orphan lessons)
- **provenance** — durable, shared origin (in-repo evidence / Tier-A section / commit subject / stated owner policy). Never a `~/.claude` path or a bare commit SHA.
- **verified** — date + the ground truth checked

## Class 1 — Code & design quality, project invariants

### C1-01 — no-backward-compat
- **check:** A fix/change carries no backward-compat clause; a path the change makes unreachable is deleted (with its tests/docs), not preserved "just in case."
- **signal:** parentheticals like "(some downstream still supports the old form)", "defensive fallback for legacy X"; `(when present)` guards wrapped around a now-unconditional contract; dead branches kept defensively.
- **severity:** should-fix
- **applies-to:** any
- **ssot:** —
- **provenance:** owner policy: fixes carry no backward-compat — pure-owner-policy lesson, no in-repo SSoT.
- **verified:** 2026-06-06 — owner policy current; the rule's validity rests on the no-back-compat policy itself, not on a code-compliance count. (Durable corroboration only, not the basis: commit subject "refactor: introduce PyYAML, retire the two hand-rolled YAML parsers".) "single-owner" rejected as ssot (absent from all committed docs).

### C1-02 — no-silent-transformation
- **check:** Consumer code composes producer data (filelist entries, paths, IDs, schema fields) verbatim; it does not silently strip/normalize/transform it. A cross-stage contract is expressible in one sentence.
- **signal:** `basename`, path-stripping, or regex-normalization applied to producer **filelist or path-handoff entries** in `bootstrap_*.sh` / `derive_*.py` / composers. (Top-name inference via `basename` is NOT this anti-pattern.)
- **severity:** must-fix
- **applies-to:** scripts, py-core
- **ssot:** —
- **provenance:** owner review 2026-05-09 of cross-stage filelist handling; fixed by the "drop the strip everywhere; entries paths-relative-to-canonical" change.
- **verified:** 2026-06-05 — `grep basename` across `skills/*/scripts` + `framework/scripts` shows basename only on top-name inference / agent-id derivation, not on filelist entries.

### C1-03 — no-skill-decided-BLOCKED
- **check:** A skill's result envelope never sets `status=blocked`; a stage that cannot complete routes via `status=fail` + `fail_reason`, reserving BLOCKED for the harness-level sub-Task carve-out only.
- **signal:** a result envelope emitting `status: blocked`, or skill prose instructing itself to declare BLOCKED, where a routable `status=fail` + `fail_reason` belongs.
- **severity:** should-fix
- **applies-to:** py-core, result-schema
- **ssot:** ARCHITECTURE.md → "Sub-Task `STATUS: BLOCKED` carve-out"
- **provenance:** ARCHITECTURE.md, §6.3.1 Fan-out dispatch privilege
- **verified:** 2026-06-05 — anchor "carve-out" resolves in ARCHITECTURE.md; the para says envelope `result.json.status=blocked` is schema-forbidden and the dispatching skill instead writes `status=fail` + `fail_reason`, with `STATUS: BLOCKED` only a harness-level sub-Task signal.

### C1-04 — simplicity / no-speculation
- **check:** Minimum code that solves the problem; no abstraction for single use, no unrequested flexibility/config, no error-handling for impossible cases; touch only what the task requires (surgical).
- **signal:** a new abstraction/flag/config not asked for, defensive handling of impossible states, "improving" adjacent unrelated code in a change.
- **severity:** should-fix
- **applies-to:** any
- **ssot:** —
- **provenance:** owner policy (simplicity / surgical-changes / no-speculation) — pure-owner-policy lesson, no in-repo SSoT (no committed repo doc owns this rule).
- **verified:** 2026-06-05 — owner policy; no committed doc states this rule (the only tracked term-hits are an incidental `YAGNI` config comment and a `for simplicity` test comment), so ssot: —.

### C1-05 — audit-dont-grandfather
- **check:** When overhauling a config/registry file, EXISTING entries are re-justified against current evidence (the no-speculation bar applies to them too), not grandfathered in.
- **signal:** config/registry entries kept during an overhaul with no current evidence/consumer; "leave it, it predates us" reasoning.
- **severity:** should-fix
- **applies-to:** any
- **ssot:** —
- **provenance:** owner policy / current practice (config overhauls re-justify each entry) — no in-repo SSoT.
- **verified:** 2026-06-06 — owner policy current; the rule's validity rests on the audit-don't-grandfather policy itself, not on commit-compliance. (Durable corroboration only: "docs(specification): re-judge genuine scenarios to two-wave flow".)

### C1-06 — fail-loud-on-bad-input
- **check:** A producer/consumer script (`bootstrap_*.sh`, `derive_*.py`, a parser) validates the REQUIRED inputs of its contract and aborts with a clear error when one is missing/empty/malformed — it does not silently fall through to emit a degraded or wrong artifact. (Optional fields may default; a *warned* graceful degradation is not a violation.)
- **signal:** a `bootstrap_*.sh` without `set -euo pipefail`; a `derive_*.py` reading a REQUIRED field with a silent default (`.get(k, "")` / `or []`) and continuing instead of raising; a missing required input file that falls through rather than exiting non-zero with a named stderr message.
- **severity:** must-fix
- **applies-to:** scripts, py-core
- **ssot:** —
- **provenance:** commit subjects "fail loud on drift", "derive_scaffold … fails loud on empty", "bootstrap fail-closed", "exit on missing report", "driver-layer hardening (pipefail…)". ARCHITECTURE §5.6 "Validation doctrine" governs `result.json`/event + advisory-artifact validation, NOT this script-input layer — so orphan.
- **verified:** 2026-06-05 — 4/4 `bootstrap_*.sh` carry `set -euo pipefail` and exit on missing netlist/filelist; `derive_constraints.py` `_fail()` exits non-zero+stderr on every malformed table field; `derive_scaffold.py` raises on empty `interface.signals`.

### C1-07 — orchestrator-stage-isolation
- **check:** The orchestration audit boundary holds — a Task-dispatched stage sub-Task never calls `Task()` itself (Level-2 dispatch forbidden), and the Orchestrator never does a full-file Read of a Task-dispatched stage's SKILL.md (those six stages load their own skill inside the subagent).
- **signal:** a `Task()` call inside a fan-out sub-Task; the Orchestrator `Read`-ing a Task-dispatched stage's SKILL.md to inline its work; a stage moved across the main-thread / Task-dispatched line without updating the isolation gate.
- **severity:** must-fix
- **applies-to:** skill-md, py-core
- **ssot:** ARCHITECTURE.md → "#### 6.3.1 Fan-out dispatch privilege"
- **provenance:** ARCHITECTURE.md §2.2 (Level-2 forbidden / audit boundary) + §5.3 (no full-file Orchestrator read) + §6.3.1.
- **verified:** 2026-06-05 — anchor "#### 6.3.1 Fan-out dispatch privilege" resolves (L395); §2.2 (L88) + §5.3 (L306) state Level-2-forbidden + no-Orchestrator-full-read.

### C1-08 — resume-rework-idempotency
- **check:** Every re-entry point — session-resume, `promote()` retry, rework re-dispatch, reap — is idempotent: re-running does not rewrite already-on-disk products, `promote()` re-links to the same inodes, a run staled mid-execution is discarded at reap (not promoted), and skills track progress via `result.json` presence + canonical-vs-`runs/` promotion with NO custom partial-completion disk marker.
- **signal:** a new `cmd_*`/write/promote path with no partial-promote repair or self-listed-artifact skip; a skill session-resume branch that re-derives/overwrites existing canonical artifacts (or re-asks a frozen input like `brainstorm.md`); a custom disk marker tracking partial completion; a `promote()` on a non-success/staled path.
- **severity:** should-fix
- **applies-to:** py-core, skill-md
- **ssot:** docs/skill-branch-routing-design.md → "### 3.4 P4 — Idempotency by design"
- **provenance:** ARCHITECTURE.md §7.2 (promote idempotent) + `artifacts.py` `promote()` self-listed guard + `state.py` cascade-stale reap + the `### Session-resume semantics` blocks in specification / simulation-plan.
- **verified:** 2026-06-05 — anchor "### 3.4 P4 — Idempotency by design" resolves (skill-branch-routing-design.md L31); ARCHITECTURE §7.2 (L481) states promote idempotency; guards confirmed in `artifacts.py` / `state.py`.

### C1-09 — state-write-order
- **check:** A state-mutating `state.py` command writes event-first — `append_event` precedes the single `write_task` — following the validate(in-memory) → event → state phase order; `write_task` never precedes its matching `append_event`.
- **signal:** a `cmd_*` path that updates `task.json` before (or without) appending the corresponding event; state written then event appended.
- **severity:** must-fix
- **applies-to:** py-core
- **ssot:** ARCHITECTURE.md → "### 4.6 Write-order invariant"
- **provenance:** ARCHITECTURE.md §4.6 + CONTRIBUTING.md "Modifying `state.py`" (event-first rule).
- **verified:** 2026-06-06 — anchor "### 4.6 Write-order invariant" resolves (ARCHITECTURE.md L251); CONTRIBUTING "Modifying `state.py`" heading resolves (L17).

### C1-10 — determinism-strata-separation
- **check:** `state.py` holds no routing/judgment logic; `route.py` is a pure function (no state, opens no files); all rework/scheduling decision logic lives only in `orchestrate.py` / `route.py`.
- **signal:** an `if upstream X start Y` routing branch added to `state.py`; `route.py` calling `open()` / reading `task.json` or carrying mutable state; a category→target map copied outside `route.py`.
- **severity:** must-fix
- **applies-to:** py-core
- **ssot:** ARCHITECTURE.md → "### 2.4 Core design principles"
- **provenance:** ARCHITECTURE.md §2.3/§2.4 (determinism strata) + CONTRIBUTING.md "Modifying `state.py`" rule 1 (no routing logic in state.py).
- **verified:** 2026-06-06 — anchor "### 2.4 Core design principles" resolves (L107); CONTRIBUTING "Modifying `state.py`" present (L17).

### C1-11 — eligibility-recheck-at-write
- **check:** `cmd_start` re-checks eligibility at write time and returns `ok:false` if state shifted since the reducer's scan; the reducer's `eligible()` is informational only; a caller handles `ok:false` (log the skip + re-query), never acting on the scan alone.
- **signal:** a dispatch path acting on the reducer's `eligible()` result with no `cmd_start` `ok:false` handling — a TOCTOU dispatch race.
- **severity:** must-fix
- **applies-to:** py-core, scripts
- **ssot:** ARCHITECTURE.md → "### 5.5 Architectural commitments embedded in this loop"
- **provenance:** ARCHITECTURE.md §5.3 (`cmd_start` is eligibility truth) + §5.5.
- **verified:** 2026-06-06 — anchors "### 5.3 Executing a `DISPATCH` / `REWORK` action" (L298) + "### 5.5 Architectural commitments embedded in this loop" (L325) resolve.

### C1-12 — scripted-verdict-gate
- **check:** A stage whose pass/fail (or PPA-threshold) verdict is a *mechanical* function of tool-report numbers/markers computes that verdict in a deterministic parser script (with a `tests/unit/` test) and folds the script's output into `result.json`; SKILL.md *runs* the parser and never instructs the LLM to read the report and judge the gate by eye. Genuine-judgment verdicts that are not mechanically determinable (failure clustering, semantic intent review) are carved out.
- **signal:** SKILL.md prose telling the LLM to "inspect the report and decide if timing/area/power is met" or to classify on a displayed slack number, with no parser owning the verdict; a gate criterion (`slack≥0`, `error-count==0`, `power≤budget`, worst-of-N-groups) expressed only as LLM instructions; a gate config that bakes in blanket waivers masking real violations; a new gate script with no `tests/unit/test_*_parser.py`.
- **severity:** should-fix
- **applies-to:** scripts, skill-md
- **ssot:** —
- **provenance:** in-repo pattern — `synthesis_rpt_parser.py` / `timing_rpt_parser.py` / `power_rpt_parser.py` / lint-cdc `collect_report.py`, each owning its stage verdict with a unit test; commit subjects "script PPA extract+gate (fail-loud), fix multi-group slack false-pass" + "power_rpt_parser owns verdict + result assembly". Complements C1-10 (orchestration-layer determinism) at the stage-verdict layer; no Tier-A doc owns it → orphan.
- **verified:** 2026-06-10 — timing-analysis SKILL.md "self-judge … via `timing_rpt_parser.py` — never by eye" (L8) + "the parser owns this; do not hand-classify" (L24); synthesis parser takes the `min` Critical Path Slack across all clock-group blocks (the false-pass fix); power "exit code is the pass/fail truth"; 4 parsers + 4 `tests/unit/test_*_parser.py` present.

## Class 2 — Skill / content hygiene & conventions

### C2-01 — skill-md-formatting-conventions
- **check:** A SKILL.md follows the §4.6 universal formatting conventions: the H1 is a concise Title Case concept name (no `name:` slug echo in parentheses, no enumeration of the skill's internal steps/outputs); top-level Workflow steps are `### Step N: <Title>` H3 headings (colon separator; orchestrator exempt — descriptive block headings, no Step numbering), never a numbered `1.`/`2.` markdown list (numbered lists are for sub-steps only); H2 are the canonical field titles, never `## 1.`-numbered.
- **signal:** H1 like `# Verification Planning (simulation-plan)` (slug echo) or `# UVM Compile + Smoke + Regression …` (step enumeration); top-level Workflow steps written as a numbered `1.`/`2.` list instead of `### Step N:` headings; a `## 1.`-style numbered H2.
- **severity:** should-fix
- **applies-to:** skill-md
- **ssot:** docs/skill-field-contract-design.md → "### 4.6 Universal formatting conventions"
- **provenance:** docs/skill-field-contract-design.md §4.6 (H1-title + Workflow Step-N headings + numbered-list rule) + §4.3.7 (orchestrator Step-heading exemption) + §4.7 compliance checklist.
- **verified:** 2026-06-10 — anchor "### 4.6 Universal formatting conventions" resolves; §4.6 carries both the H1-title bullet and the Workflow `### Step N:` heading + numbered-list-for-sub-steps bullets; §4.3.7 holds the orchestrator exemption; §4.7 checklist lists the Step-N item.

### C2-02 — test-obligation-routing-verdict
- **check:** A new routing-verdict field (in `result.json` / event payloads) ships with a schema update AND a `test_state.py` coverage test in the same change.
- **signal:** a diff adding a verdict field to a schema or `state.py` write path with no matching `tests/unit/test_state.py` edit.
- **severity:** must-fix
- **applies-to:** py-core, result-schema
- **ssot:** CONTRIBUTING.md → "Validating new structured outputs" (routing-verdict bullet)
- **provenance:** CONTRIBUTING.md, "Validating new structured outputs".
- **verified:** 2026-06-05 — heading "Validating new structured outputs" resolves in CONTRIBUTING.md; routing-verdict bullet ("coverage test") present.

### C2-03 — test-obligation-advisory-artifact
- **check:** A skill's own descriptive/advisory artifact ships a `scripts/validate_*.py` producer self-gate the skill runs before emitting it.
- **signal:** a new advisory artifact (ANALYSIS/scaffold-like) with no `scripts/validate_*.py` and no "run validator before emit" step in SKILL.md.
- **severity:** should-fix
- **applies-to:** scripts, skill-md
- **ssot:** CONTRIBUTING.md → "Validating new structured outputs" (advisory-artifact bullet)
- **provenance:** CONTRIBUTING.md, "Validating new structured outputs"; pattern in `skills/simulation-triage/scripts/validate_analysis.py`.
- **verified:** 2026-06-05 — heading "Validating new structured outputs" resolves; advisory-artifact bullet ("producer self-gate") present.

### C2-04 — runtime-content-hygiene
- **check:** runtime-loaded content (a SKILL.md, `references/`, or runtime `scripts/` file) carries no evolution/version history, no citation that resolves to no committed file, no vestigial VeriPower-internal version label, no pointer to an uncommitted dev/design doc, and no coupling to another project's paths.
- **signal:** a section-number citation that resolves to no committed file; a pointer to an uncommitted design/plan doc (a dev-workspace spec/plan not under version control); "in the previous plan/version" history prose; a vestigial VeriPower-internal version label (e.g. a stale `v3`/`v4` tag) with no current referent — NOT an external file-format version such as `SDF v3.0`; a path belonging to a different repo/project.
- **severity:** should-fix
- **applies-to:** skill-md, references, scripts
- **ssot:** —
- **provenance:** owner review checklist (runtime-content hygiene) — review discipline, no in-repo SSoT.
- **verified:** 2026-06-05 — qualified residue grep across skills + framework returned 0 (no dead section-markers / dev-doc history residue).

### C2-05 — skill-self-containment
- **check:** A stage skill describes only *itself* (its inputs, outputs, internal rules) — not its orchestration: no DAG / dispatch / sibling-stage vocabulary and no naming of orchestration-layer internals (`state.py` / `events.jsonl` / `task.json`); the rule applies recursively across the whole `skills/<name>/` tree.
- **signal:** stage-skill prose naming who calls it / when it is dispatched / a sibling stage ("the downstream consumer"), or referencing `state.py` / `events.jsonl` / `task.json` / `Orchestrator` / `DAG`.
- **severity:** should-fix
- **applies-to:** skill-md, references
- **ssot:** docs/skill-self-containment-design.md → "## 3. Principles" (P1 describe-self / P2 recursive scope)
- **provenance:** docs/skill-self-containment-design.md §3.
- **verified:** 2026-06-05 — anchor "## 3. Principles" resolves; P1 ("Describe self, not orchestration") and P2 (recursive over the whole `skills/<name>/` tree) own the self-containment rule.

### C2-06 — references-organization
- **check:** Reference material follows the organization principles: every rule has one canonical home (cross-references link, never duplicate); `references/` is a flat directory (no nested subdirs); a skill's private `references/` does not cross-reference another skill's private references.
- **signal:** the same rule duplicated across two docs; a nested `references/` subdirectory; a skill's `references/` file pointing into another skill's private `references/` via an `@`-path or file-path cross-link (a `veripower:`-namespace reference, or a markdown link to a shared `docs/` / `framework/references/` doc, is fine).
- **severity:** should-fix
- **applies-to:** skill-md, references
- **ssot:** docs/skill-references-organization-design.md → "## 3. Principles" (P1 single canonical home / P3 one-layer references)
- **provenance:** docs/skill-references-organization-design.md §3.
- **verified:** 2026-06-05 — anchor "## 3. Principles" resolves; P1 (single canonical home, no duplication) and P3 (flat one-layer `references/`) own the organization rule.

### C2-07 — skill-frontmatter
- **check:** SKILL.md frontmatter is the 2-key contract — `name` + `description` only — per the frontmatter design; no forbidden key (e.g. `allowed-tools`) is present, AND the `name`/`description` content obeys the frontmatter conventions.
- **signal:** a `name` not kebab-case / >3 segments / carrying a namespace prefix / not matching the skill directory; a `description` missing its `not for` clause, written in first person, a workflow summary rather than a when-to-use trigger, or carrying <2 domain-specific keywords; or a forbidden key (e.g. `allowed-tools`) present in frontmatter.
- **severity:** should-fix
- **applies-to:** skill-md
- **ssot:** docs/skill-frontmatter-design.md → "## 3. Principles" (§3.1 name format / §3.2 description shape / §3.3 when-to-use-not-workflow / §3.4 keyword coverage / §3.5 English)
- **provenance:** docs/skill-frontmatter-design.md §3.1–§3.5.
- **verified:** 2026-06-06 — anchor "## 3. Principles" resolves (frontmatter-design L27); §3.1–§3.5 own name format, description shape, when-to-use, keyword coverage, and English.

### C2-08 — language-posture
- **check:** content matches the language posture — the full Surface-1 set (runtime-LLM-consumed) is English: SKILL.md, `references/*.md`, `skills/*/scripts/*`, `skills/*/templates/*`, `framework/scripts/state.py`, `framework/references/prompts/*.tpl`, `*.schema.json` descriptions, and `tests/unit/*.py` assertion strings — and committed `docs/*.md` are English by standardization policy.
- **signal:** CJK characters in any Surface-1 file: a SKILL.md, `references/*.md`, a runtime `scripts/*` or `templates/*` file, `state.py`, a `*.tpl`, a `*.schema.json` `description`, a `tests/unit/*.py` assertion string, or a committed `docs/*.md`.
- **severity:** should-fix
- **applies-to:** skill-md, references, scripts, py-core, result-schema, docs
- **ssot:** docs/language-posture-design.md → "## 3. Surface 1 — runtime-LLM-consumed content (English)" (Surface-1 English rule)
- **provenance:** docs/language-posture-design.md §3 (full Surface-1 set) + §7 (`docs/*.md` English by standardization policy).
- **verified:** 2026-06-06 — anchor "## 3. Surface 1 — runtime-LLM-consumed content (English)" resolves (L29); §3 enumerates scripts/templates/state.py/*.tpl/schemas/tests as Surface 1; §7 states `docs/*.md` are English-by-standardization.

### C2-09 — result-schema
- **check:** A `result.schema.json` change keeps `stage_specific.required[]` minimum-sufficient (every required field answers the §4 test questions), adds no orchestration-internal or artifact-duplicating field, and keeps each `description`'s consumer relationship accurate. `schema_version` is the shared completion-certificate (R1) contract version, pinned uniformly across all nine stage schemas; it bumps ONLY on a cross-stage envelope-contract change (a universal R1/R2 field, the `status` enum, the artifact-manifest shape) — NOT for a stage-local `stage_specific` (R3) add/remove/retype, which the per-stage schema's `properties` + `status` if/then versions (co-updated with its consumers + test fixtures).
- **signal:** a `*.schema.json` diff adding a `required` field that isn't load-bearing or that duplicates another artifact; a `description` with "may be useful" hand-waving; a `stage_specific` removal/retype not co-updated in its consumers + test fixtures; or a shared envelope-contract change (universal field / `status` enum / artifact-manifest shape) with no `schema_version` bump. (A status-gated `stage_specific` addition with no `schema_version` bump is NOT a violation.)
- **severity:** should-fix
- **applies-to:** result-schema, py-core
- **ssot:** docs/result-schema-design.md → "## 7. Compliance checklist (for schema review)" + "## 8. Process for changing a schema" (what `schema_version` versions + bump triggers)
- **provenance:** docs/result-schema-design.md §7 + §8 (`schema_version` = shared envelope-tier contract version; `stage_specific` evolution is versioned by the per-stage schema + co-update, not a bump).
- **verified:** 2026-06-08 — all nine stage schemas pin `schema_version {const: 1}`; no consumer branches on its value (grep of framework/scripts); no stage redesign (synthesis / lint-cdc / rtl-design / specification / timing-analysis) has bumped it for a `stage_specific` addition. §8 reconciled to scope bumps to the shared envelope contract (the practice this entry now codifies); anchors "## 7. Compliance checklist (for schema review)" + "## 8. Process for changing a schema" resolve.

### C2-10 — workdir-path-contract
- **check:** A SKILL.md (and its scripts via `--workdir`) addresses files through the dispatcher-injected `{workdir}` / `{module}` placeholders — never a hardcoded `asic/<M>` / `asic/<module>` angle-bracket fragment, a literal module-named path (`asic/alu16/…`), or a `runs/<N>` path.
- **signal:** a SKILL.md or its I/O table containing a hardcoded `asic/<module>` / `asic/<M>` / `runs/<N>` fragment or a literal module-named path, instead of the injected `{workdir}` / `{module}` placeholder.
- **severity:** should-fix
- **applies-to:** skill-md, scripts
- **ssot:** docs/skill-field-contract-design.md → "#### 4.3.5 Input Artifacts"
- **provenance:** docs/skill-field-contract-design.md §4.3.5–§4.3.6 ("SKILL.md must never hard-code `asic/<M>`, `asic/<module>`, or `runs/<N>` … use `{workdir}` exclusively"); uniform across the 9 SKILL.md Iron Rules.
- **verified:** 2026-06-05 — anchor "#### 4.3.5 Input Artifacts" resolves (L204); §4.3.6 (L256) states paths are relative to `{workdir}` with no `asic/<M>` or `runs/<N>` hard-coding.

### C2-11 — early-fail-required-fields
- **check:** A `status=fail` result still emits every schema-required `stage_specific` field (the per-stage `result.schema.json` if/then-gates them on `status`); a stage must not drop required fields on the early-fail path.
- **signal:** a stage SKILL.md or `result.schema.json` whose `status=fail` branch omits a `stage_specific` field the schema requires; a missing `if status=fail then required[...]` gate.
- **severity:** must-fix
- **applies-to:** result-schema, skill-md
- **ssot:** ARCHITECTURE.md → "### 6.2 `failure_kind` envelope obligation"
- **provenance:** ARCHITECTURE.md §6.2 + per-stage `result.schema.json` if/then gates; commit family "if/then-gate fail_reason across 7 stages", "mandate ppa_actual/violations on early-fail".
- **verified:** 2026-06-06 — anchor "### 6.2 `failure_kind` envelope obligation" resolves (L372); per-stage schemas if/then-gate `stage_specific` on `status`.

### C2-12 — branch-coverage
- **check:** If a SKILL.md Step 1 defines N routing branches, every downstream step states which branches it applies to (an inline scope label) or the skill declares scope-identity ("Steps 2–N identical across branches"); linear downstream after a multi-branch Step 1 is a defect.
- **signal:** a multi-branch Step 1 followed by downstream steps carrying no per-branch qualifier and no scope-identity statement.
- **severity:** should-fix
- **applies-to:** skill-md
- **ssot:** docs/skill-branch-routing-design.md → "### 3.3 P3 — Branch coverage = step coverage"
- **provenance:** docs/skill-branch-routing-design.md §3.3.
- **verified:** 2026-06-06 — anchor "### 3.3 P3 — Branch coverage = step coverage" resolves (L23).

### C2-13 — new-stage-topology-registration
- **check:** A new DAG stage updates all four `topology.py` maps (`FORWARD_PRIORITY`, `PREREQ_OF`, `SKILL_OF`, `_RESULT_DIR`), adds `tests/scenarios/<stage>/`, and updates `skills/design-flow/SKILL.md` if it introduces new scheduling semantics.
- **signal:** a stage added to one `topology.py` map but not all four; a new stage with no `tests/scenarios/<stage>/`; new scheduling semantics with a stale `design-flow` SKILL.md.
- **severity:** should-fix
- **applies-to:** py-core, scripts, skill-md
- **ssot:** CONTRIBUTING.md → "Adding or modifying a stage skill"
- **provenance:** CONTRIBUTING.md "Adding or modifying a stage skill" (items 3–5).
- **verified:** 2026-06-06 — heading "Adding or modifying a stage skill" resolves (CONTRIBUTING.md L5).

## Class 3 — Verification & epistemic discipline

### C3-01 — claims-are-grep-backed
- **check:** Every factual claim the change makes about the codebase (commit message, comments, docs) is backed by current ground truth — a "shared"/"used-everywhere" claim is backed by an actual consumer grep, a cited file:line / symbol / section anchor resolves, and a stated count matches what the diff changed.
- **signal:** a "shared infra" / "all consumers do X" claim whose §2 consumer-grep returns no citer; a file:line / symbol / section anchor in the change's text that does not resolve; a numeric count the diff's own content contradicts.
- **severity:** consider
- **applies-to:** any
- **ssot:** —
- **provenance:** owner review discipline (grep-before-sharing-claim) — pure epistemic lesson, no in-repo origin.
- **verified:** 2026-06-05 — discipline statement; no code anchor by nature.

### C3-02 — re-verify-before-done
- **check:** A change's "done / fixed / all-tests-pass / verified" claim is backed by evidence in the change itself (the command and its output, a failing-then-passing test, the resolved reference) — not asserted from intent.
- **signal:** a "done" / "all tests pass" / "fixed X" / "verified" claim in the commit message or PR text with no accompanying evidence (no command output, no test name, no diff demonstrating the fix); a success claim the change's own content contradicts.
- **severity:** consider
- **applies-to:** any
- **ssot:** —
- **provenance:** owner review discipline (re-verify before declaring done) — pure epistemic lesson, no in-repo origin.
- **verified:** 2026-06-05 — discipline statement; no code anchor by nature.

### C3-03 — verify-optimization-vs-confounds
- **check:** A claimed optimization (token/perf/size win) isolates the change from confounds — the baseline is stated, the metric measures THIS change's mechanism, and the mechanism is shown to actually engage (presence of a feature ≠ benefit).
- **signal:** a "saves N tokens" / "Y% faster" claim with no baseline; a metric that doesn't isolate the changed pillar; "added feature Z" presented as if its mere presence proves the win.
- **severity:** consider
- **applies-to:** any
- **ssot:** —
- **provenance:** owner review discipline (verify optimization against confounds) — pure epistemic lesson, no in-repo origin.
- **verified:** 2026-06-05 — discipline statement; no code anchor by nature.
