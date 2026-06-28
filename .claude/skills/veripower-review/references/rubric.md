# VeriPower Review Rubric — a defect-shape field guide

What known VeriPower violations *look like* in the wild — to sharpen recognition, not to bound the
review (see SKILL.md "Knowledge tiers" Tier B; coverage comes from the §3 worklist / §4 walk). The
guide **grows**: a review that finds a real defect no entry names files it as a gap (SKILL.md §4
ledger), and the new shape is added here.

A new entry earns its place by **sharpening perception** — distilling a rule to its testable boundary
(`check`) and naming the concrete forms a violation takes (`signal`) — not by reproducing source
prose. A rule owned by a Tier-A doc carries an `ssot` pointer and the entry distills it (does not
duplicate); an orphan lesson with no Tier-A home carries no `ssot` and states its origin in
`provenance`.

Each entry:

- **id** — class-numbered handle (`C1-01`, `C2-03`, `C3-02`)
- **check** — the rule distilled to its testable boundary (full statement lives at `ssot`)
- **signal** — the core: the concrete forms the violation takes in the wild
- **severity** — `must-fix` / `should-fix` / `consider`
- **applies-to** — surfaces to keep the shape in mind for: `any` / `skill-md` / `references` / `scripts` / `py-core` / `docs` / `result-schema` / `constraints`
- **ssot** — where the authoritative intent lives (pointer entries only; `—` for orphan lessons)
- **provenance** — orphan entries only (no `ssot`): the durable origin of the lesson

## Class 1 — Code & design quality, project invariants

### C1-01 — no-backward-compat
- **check:** A fix/change carries no backward-compat clause; a path the change makes unreachable is deleted (with its tests/docs), not preserved "just in case."
- **signal:** parentheticals like "(some downstream still supports the old form)", "defensive fallback for legacy X"; `(when present)` guards wrapped around a now-unconditional contract; dead branches kept defensively.
- **severity:** should-fix
- **applies-to:** any
- **ssot:** —
- **provenance:** owner policy — fixes carry no backward-compat (no in-repo SSoT).

### C1-02 — no-silent-transformation
- **check:** Consumer code composes producer data (filelist entries, paths, IDs, schema fields) verbatim; it does not silently strip/normalize/transform it. A cross-stage contract is expressible in one sentence.
- **signal:** `basename`, path-stripping, or regex-normalization applied to producer **filelist or path-handoff entries** in `bootstrap_*.sh` / `derive_*.py` / composers. (Top-name inference via `basename` is NOT this anti-pattern.)
- **severity:** must-fix
- **applies-to:** scripts, py-core
- **ssot:** —
- **provenance:** owner review of cross-stage filelist handling — entries stay paths-relative-to-canonical, no stripping.

### C1-03 — no-skill-decided-BLOCKED
- **check:** A skill's result envelope never sets `status=blocked`; a stage that cannot complete routes via `status=fail` + `fail_reason`, reserving BLOCKED for the harness-level sub-Task carve-out only.
- **signal:** a result envelope emitting `status: blocked`, or skill prose instructing itself to declare BLOCKED, where a routable `status=fail` + `fail_reason` belongs.
- **severity:** should-fix
- **applies-to:** py-core, result-schema
- **ssot:** ARCHITECTURE.md → "Sub-Task `STATUS: BLOCKED` carve-out"

### C1-04 — simplicity / no-speculation
- **check:** Minimum code that solves the problem; no abstraction for single use, no unrequested flexibility/config, no error-handling for impossible cases; touch only what the task requires (surgical).
- **signal:** a new abstraction/flag/config not asked for, defensive handling of impossible states, "improving" adjacent unrelated code in a change.
- **severity:** should-fix
- **applies-to:** any
- **ssot:** —
- **provenance:** owner policy (simplicity / surgical-changes / no-speculation) — no committed repo doc owns it.

### C1-05 — audit-dont-grandfather
- **check:** When overhauling a config/registry file, EXISTING entries are re-justified against current evidence (the no-speculation bar applies to them too), not grandfathered in.
- **signal:** config/registry entries kept during an overhaul with no current evidence/consumer; "leave it, it predates us" reasoning.
- **severity:** should-fix
- **applies-to:** any
- **ssot:** —
- **provenance:** owner policy / current practice — config overhauls re-justify each entry.

### C1-06 — fail-loud-on-bad-input
- **check:** A producer/consumer script (`bootstrap_*.sh`, `derive_*.py`, a parser) validates the REQUIRED inputs of its contract and aborts with a clear error when one is missing/empty/malformed — it does not silently fall through to emit a degraded or wrong artifact. (Optional fields may default; a *warned* graceful degradation is not a violation.)
- **signal:** a `bootstrap_*.sh` without `set -euo pipefail`; a `derive_*.py` reading a REQUIRED field with a silent default (`.get(k, "")` / `or []`) and continuing instead of raising; a missing required input file that falls through rather than exiting non-zero with a named stderr message.
- **severity:** must-fix
- **applies-to:** scripts, py-core
- **ssot:** —
- **provenance:** in-repo evidence — every stage `bootstrap` verb fail-closes on missing/empty inputs; the spec `derive-constraints` verb's `_fail()` / simulation's `render-scaffold` raise on malformed/empty required fields. (ARCHITECTURE §5.6 "Validation doctrine" governs the `result.json`/event + advisory-artifact layer, NOT this script-input layer — so orphan.)

### C1-07 — orchestrator-stage-isolation
- **check:** The orchestration audit boundary holds — a Task-dispatched stage sub-Task never calls `Task()` itself (Level-2 dispatch forbidden), and the Orchestrator never does a full-file Read of a Task-dispatched stage's SKILL.md (those six stages load their own skill inside the subagent).
- **signal:** a `Task()` call inside a fan-out sub-Task; the Orchestrator `Read`-ing a Task-dispatched stage's SKILL.md to inline its work; a stage moved across the main-thread / Task-dispatched line without updating the isolation boundary.
- **severity:** must-fix
- **applies-to:** skill-md, py-core
- **ssot:** ARCHITECTURE.md → "#### 6.3.1 Fan-out dispatch privilege" (+ §2.2 Level-2-forbidden / audit boundary, §5.3 no full-file Orchestrator read)

### C1-08 — resume-rework-idempotency
- **check:** Every re-entry point — session-resume, `promote()` retry, rework re-dispatch, reap — is idempotent: re-running does not rewrite already-on-disk products, `promote()` re-links to the same inodes, a run staled mid-execution is discarded at reap (not promoted), and skills track progress via `result.json` presence + canonical-vs-`runs/` promotion with NO custom partial-completion disk marker.
- **signal:** a new `cmd_*`/write/promote path with no partial-promote repair or self-listed-artifact skip; a skill session-resume branch that re-derives/overwrites existing canonical artifacts (or re-asks a frozen input like `brainstorm.md`); a custom disk marker tracking partial completion; a `promote()` on a non-success/staled path.
- **severity:** should-fix
- **applies-to:** py-core, skill-md
- **ssot:** docs/skill-branch-routing-design.md → "### 3.4 P4 — Idempotency by design" (+ ARCHITECTURE §7.2 promote idempotency)

### C1-09 — state-write-order
- **check:** A state-mutating `state.py` command writes event-first — `append_event` precedes the single `write_task` — following the validate(in-memory) → event → state phase order; `write_task` never precedes its matching `append_event`.
- **signal:** a `cmd_*` path that updates `task.json` before (or without) appending the corresponding event; state written then event appended.
- **severity:** must-fix
- **applies-to:** py-core
- **ssot:** ARCHITECTURE.md → "### 4.6 Write-order invariant" (+ CONTRIBUTING.md "Modifying `state.py`" event-first rule)

### C1-10 — determinism-strata-separation
- **check:** `state.py` holds no routing/judgment logic; `route.py` is a pure function (no state, opens no files); all rework/scheduling decision logic lives only in `orchestrate.py` / `route.py`.
- **signal:** an `if upstream X start Y` routing branch added to `state.py`; `route.py` calling `open()` / reading `task.json` or carrying mutable state; a category→target map copied outside `route.py`.
- **severity:** must-fix
- **applies-to:** py-core
- **ssot:** ARCHITECTURE.md → "### 2.4 Core design principles" (§2.3/§2.4 determinism strata; + CONTRIBUTING.md "Modifying `state.py`" rule 1)

### C1-11 — eligibility-recheck-at-write
- **check:** `cmd_dispatch` re-checks eligibility at write time and returns `ok:false` if state shifted since the decider's scan; the decider's `eligible()` is informational only; a caller handles `ok:false` (log the skip + re-query), never acting on the scan alone.
- **signal:** a dispatch path acting on the decider's `eligible()` result with no `cmd_dispatch` `ok:false` handling — a TOCTOU dispatch race.
- **severity:** must-fix
- **applies-to:** py-core, scripts
- **ssot:** ARCHITECTURE.md → "### 5.5 Architectural commitments embedded in this loop" (+ §5.3 `cmd_dispatch` is eligibility truth)

### C1-12 — scripted-verdict-gate
- **check:** A stage whose pass/fail (or PPA-threshold) verdict is a *mechanical* function of tool-report numbers/markers computes that verdict in a deterministic parser script (with a `tests/unit/` test) and folds the script's output into `result.json`; SKILL.md *runs* the parser and never instructs the LLM to read the report and judge the gate by eye. Genuine-judgment verdicts (failure clustering, semantic intent review) are carved out.
- **signal:** SKILL.md prose telling the LLM to "inspect the report and decide if timing/area/power is met" or to classify on a displayed slack number, with no parser owning the verdict; a gate criterion (`slack≥0`, `error-count==0`, `power≤budget`, worst-of-N-groups) expressed only as LLM instructions; a gate config that bakes in blanket waivers masking real violations; a new gate verdict with no `tests/unit/test_*_result.py`.
- **severity:** should-fix
- **applies-to:** scripts, skill-md
- **ssot:** —
- **provenance:** in-repo pattern — the synthesis / timing / power-analysis `finalize` verbs / lint-cdc `collect_report.py`, each owning its stage verdict with a unit test. Complements C1-10 at the stage-verdict layer; no Tier-A doc owns it → orphan.

### C1-13 — command-action-name-parity
- **check:** A control-plane operation carries one root across its `state.py` command and the decider's action (`dispatch`/`DISPATCH`, `reap`/`REAP`, `rework`/`REWORK`); events stay named for what they record (`dispatch`, `outcome`, `cascade`). A coined term (glossary / ARCHITECTURE prose) is never defined 1:1 as a single command of a different name — a term equals its code identifier, or carries its own action/event anchor.
- **signal:** a new `state.py` command whose root differs from its `decide`-emitted action; a glossary/ARCHITECTURE term defined as "= `state.py <cmd>`" / "= `orchestrate.py <cmd>`" whose own name doesn't match that command and which no action/event anchors.
- **severity:** should-fix
- **applies-to:** py-core, docs
- **ssot:** ARCHITECTURE.md → "### 4.5 Event types" (its "Naming invariant" para owns the command==action-root rule)

## Class 2 — Skill / content hygiene & conventions

### C2-01 — skill-md-formatting-conventions
- **check:** A SKILL.md follows the §4.6 universal formatting conventions: the H1 is a concise Title Case concept name (no `name:` slug echo in parentheses, no enumeration of the skill's internal steps/outputs); top-level Workflow steps are `### Step N: <Title>` H3 headings (N a sequential integer; a sub-step is a numbered list inside an integer step, not its own H3; colon separator; orchestrator exempt — descriptive block headings, no Step numbering), never a numbered `1.`/`2.` markdown list; H2 are the canonical field titles, never `## 1.`-numbered.
- **signal:** H1 like `# Verification Planning (simulation-plan)` (slug echo) or `# UVM Compile + Smoke + Regression …` (step enumeration); a **decimal** top-level Step heading — `### Step 6.5:` / `### Step 3.5:` — where peer steps must be integers (renumber, don't decimal-insert); top-level Workflow steps written as a numbered `1.`/`2.` list instead of `### Step N:` headings; a `## 1.`-style numbered H2.
- **severity:** should-fix
- **applies-to:** skill-md
- **ssot:** docs/skill-field-contract-design.md → "### 4.6 Universal formatting conventions" (+ §4.3.7 orchestrator exemption, §4.7 checklist)

### C2-02 — test-obligation-routing-verdict
- **check:** A new routing-verdict field (in `result.json` / event payloads) ships with a schema update AND a `test_state.py` coverage test in the same change.
- **signal:** a diff adding a verdict field to a schema or `state.py` write path with no matching `tests/unit/test_state.py` edit.
- **severity:** must-fix
- **applies-to:** py-core, result-schema
- **ssot:** CONTRIBUTING.md → "Validating new structured outputs" (routing-verdict bullet)

### C2-03 — test-obligation-advisory-artifact
- **check:** A skill's own descriptive/advisory artifact ships a `scripts/validate_*.py` producer self-gate the skill runs before emitting it.
- **signal:** a new advisory artifact (ANALYSIS/scaffold-like) with no `scripts/validate_*.py` and no "run validator before emit" step in SKILL.md.
- **severity:** should-fix
- **applies-to:** scripts, skill-md
- **ssot:** CONTRIBUTING.md → "Validating new structured outputs" (advisory-artifact bullet)

### C2-04 — runtime-content-hygiene
- **check:** runtime-loaded content (a SKILL.md, `references/`, or runtime `scripts/` file) carries no evolution/version history, no citation that resolves to no committed file, no vestigial VeriPower-internal version label, no pointer to an uncommitted dev/design doc, and no coupling to another project's paths.
- **signal:** a section-number citation that resolves to no committed file; a pointer to an uncommitted design/plan doc (a dev-workspace spec/plan not under version control); "in the previous plan/version" history prose; a vestigial VeriPower-internal version label (e.g. a stale `v3`/`v4` tag) with no current referent — NOT an external file-format version such as `SDF v3.0`; a path belonging to a different repo/project.
- **severity:** should-fix
- **applies-to:** skill-md, references, scripts
- **ssot:** —
- **provenance:** owner review checklist (runtime-content hygiene) — review discipline, no in-repo SSoT.

### C2-05 — skill-self-containment
- **check:** A stage skill describes only *itself* (its inputs, outputs, internal rules) — not its orchestration: no DAG / dispatch / sibling-stage vocabulary and no naming of orchestration-layer internals (`state.py` / `events.jsonl` / `task.json` / `orchestrate.py` / `route.py` / `topology.py`); the rule applies recursively across the whole `skills/<name>/` tree.
- **signal:** stage-skill prose naming who calls it / when it is dispatched / a sibling stage ("the downstream consumer"); referencing a **sibling skill's internal step in any form** — full (`as simulation Step 4 does`, `rtl-design Step 4.4`) or abbreviated (`as sim Step 4 does`, `rtl Step 4.4`, `the simulation stage's Step 4`); or referencing `state.py` / `events.jsonl` / `task.json` / `orchestrate.py` / `route.py` / `topology.py` / `Orchestrator` / `DAG`. (A skill naming its *own* steps, and a dispatcher skill's in-role `Task` / `sub-Task` vocabulary per §6.1, are carve-outs.)
- **severity:** should-fix
- **applies-to:** skill-md, references
- **ssot:** docs/skill-self-containment-design.md → "## 3. Principles" (P1 describe-self / P2 recursive scope; §4 forbidden-keyword catalog, §6.1 dispatcher carve-out)

### C2-06 — references-organization
- **check:** Reference material follows the organization principles: every rule has one canonical home (cross-references link, never duplicate); `references/` is a flat directory (no nested subdirs); a skill's private `references/` does not cross-reference another skill's private references.
- **signal:** the same rule duplicated across two docs; a nested `references/` subdirectory; a skill's `references/` file pointing into another skill's private `references/` via an `@`-path or file-path cross-link (a `veripower:`-namespace reference, or a markdown link to a shared `docs/` / `framework/references/` doc, is fine).
- **severity:** should-fix
- **applies-to:** skill-md, references
- **ssot:** docs/skill-references-organization-design.md → "## 3. Principles" (P1 single canonical home / P3 one-layer references)

### C2-07 — skill-frontmatter
- **check:** SKILL.md frontmatter is the 2-key contract — `name` + `description` only — per the frontmatter design; no forbidden key (e.g. `allowed-tools`) is present, AND the `name`/`description` content obeys the frontmatter conventions.
- **signal:** a `name` not kebab-case / >3 segments / carrying a namespace prefix / not matching the skill directory; a `description` missing its `not for` clause, written in first person, a workflow summary rather than a when-to-use trigger, or carrying <2 domain-specific keywords; or a forbidden key (e.g. `allowed-tools`) present in frontmatter.
- **severity:** should-fix
- **applies-to:** skill-md
- **ssot:** docs/skill-frontmatter-design.md → "## 3. Principles" (§3.1 name / §3.2 description shape / §3.3 when-to-use-not-workflow / §3.4 keyword coverage / §3.5 English)

### C2-08 — language-posture
- **check:** content matches the language posture — the full Surface-1 set (runtime-LLM-consumed) is English: SKILL.md, `references/*.md`, `skills/*/scripts/*`, `skills/*/templates/*`, `framework/scripts/state.py`, `framework/references/prompts/*.tpl`, `*.schema.json` descriptions, and `tests/unit/*.py` assertion strings — and committed `docs/*.md` are English by standardization policy. A committed `.zh.md` mirror (`ARCHITECTURE.zh.md`, `GETTING-STARTED.zh.md`) is the sanctioned bilingual exception — a translation, not an independent doc, that MUST be updated in the same change as its English source (never left stale or contradicting it).
- **signal:** CJK characters in any Surface-1 file: a SKILL.md, `references/*.md`, a runtime `scripts/*` or `templates/*` file, `state.py`, a `*.tpl`, a `*.schema.json` `description`, a `tests/unit/*.py` assertion string, or a committed `docs/*.md` (excluding the sanctioned `.zh.md` mirrors); OR an English source doc changed in the diff whose committed `.zh.md` mirror is not correspondingly updated — a stale or English↔Chinese-contradicting translation (pull the mirror in as a §2 counterpart, then diff the changed sections against it).
- **severity:** should-fix
- **applies-to:** skill-md, references, scripts, py-core, result-schema, docs
- **ssot:** docs/language-posture-design.md → "## 3. Surface 1 — runtime-LLM-consumed content (English)" + "## 7. Not a Surface — project documentation" (the **Committed bilingual mirrors** paragraph — mirrors sync with their English source)

### C2-09 — result-schema
- **check:** A `result.schema.json` change keeps `stage_specific.required[]` minimum-sufficient (every required field answers the §4 test questions), adds no orchestration-internal or artifact-duplicating field, and keeps each `description`'s consumer relationship accurate. `schema_version` bumps ONLY on a cross-stage envelope-contract change (a universal R1/R2 field, the `status` enum, the artifact-manifest shape) — never for a stage-local `stage_specific` add/remove/retype.
- **signal:** a `*.schema.json` diff adding a `required` field that isn't load-bearing or that duplicates another artifact; a `description` with "may be useful" hand-waving; a `stage_specific` removal/retype not co-updated in its consumers + test fixtures; or a shared envelope-contract change (universal field / `status` enum / artifact-manifest shape) with no `schema_version` bump. (A status-gated `stage_specific` addition with no `schema_version` bump is NOT a violation.)
- **severity:** should-fix
- **applies-to:** result-schema, py-core
- **ssot:** docs/result-schema-design.md → "## 7. Compliance checklist (for schema review)" + "## 8. Process for changing a schema" (what `schema_version` versions + bump triggers)

### C2-10 — workdir-path-contract
- **check:** A SKILL.md (and its scripts via `--workdir`) addresses files through the dispatcher-injected `{workdir}` / `{module}` placeholders — never a hardcoded `asic/<M>` / `asic/<module>` angle-bracket fragment, a literal module-named path (`asic/alu16/…`), or a `runs/<N>` path.
- **signal:** a SKILL.md or its I/O table containing a hardcoded `asic/<module>` / `asic/<M>` / `runs/<N>` fragment or a literal module-named path, instead of the injected `{workdir}` / `{module}` placeholder.
- **severity:** should-fix
- **applies-to:** skill-md, scripts
- **ssot:** docs/skill-field-contract-design.md → "#### 4.3.5 Input Artifacts" (§4.3.5–§4.3.6 — paths relative to `{workdir}`, no `asic/<M>` / `runs/<N>` hard-coding)

### C2-11 — early-fail-required-fields
- **check:** A `status=fail` result still emits every schema-required `stage_specific` field (the per-stage `result.schema.json` if/then-gates them on `status`); a stage must not drop required fields on the early-fail path.
- **signal:** a stage SKILL.md or `result.schema.json` whose `status=fail` branch omits a `stage_specific` field the schema requires; a missing `if status=fail then required[...]` gate.
- **severity:** must-fix
- **applies-to:** result-schema, skill-md
- **ssot:** ARCHITECTURE.md → "### 6.2 `failure_kind` envelope obligation" (+ per-stage `result.schema.json` if/then gates)

### C2-12 — branch-coverage
- **check:** If a SKILL.md Step 1 defines N routing branches, every downstream step states which branches it applies to (an inline scope label) or the skill declares scope-identity ("Steps 2–N identical across branches"); linear downstream after a multi-branch Step 1 is a defect.
- **signal:** a multi-branch Step 1 followed by downstream steps carrying no per-branch qualifier and no scope-identity statement.
- **severity:** should-fix
- **applies-to:** skill-md
- **ssot:** docs/skill-branch-routing-design.md → "### 3.3 P3 — Branch coverage = step coverage"

### C2-13 — new-stage-topology-registration
- **check:** A new DAG stage updates all four `topology.py` maps (`FORWARD_PRIORITY`, `PREREQ_OF`, `SKILL_OF`, `_RESULT_DIR`), adds `tests/scenarios/<stage>/`, and updates `skills/design-flow/SKILL.md` if it introduces new scheduling semantics.
- **signal:** a stage added to one `topology.py` map but not all four; a new stage with no `tests/scenarios/<stage>/`; new scheduling semantics with a stale `design-flow` SKILL.md.
- **severity:** should-fix
- **applies-to:** py-core, scripts, skill-md
- **ssot:** CONTRIBUTING.md → "Adding or modifying a stage skill" (items 3–5)

### C2-14 — skill-voice
- **check:** A SKILL.md uses imperative voice for rules / steps / gates with no hedging (`must` / `never`, not `should` / `consider`); a skill with a dispatch boundary (the fan-out / orchestrator skills) names the dispatching self by role-noun ("the main thread" / "the orchestrator") and a dispatched agent by role ("the sub-Task" / "the child"), not second-person "you" (which is the voice of a single-actor skill). The same voice governs `references/*.md`, attributed by **reader-actor**: a task-contract addresses its dispatched child / sub-Task, a template its producing stage, a coding-rules file its stage agent — each as "you"; naming that reader in third person is a miss.
- **signal:** `should` / `consider` hedging where a rule or gate means `must` / `never`; a fan-out or orchestrator skill referring to the dispatching self as "you" / "your" instead of a role-noun; a `references/*.md` file naming its own reader-actor in third person — e.g. a task-contract heading or body saying "the child" / "the LLM" where the file's body addresses that same actor as "you".
- **severity:** should-fix
- **applies-to:** skill-md, references
- **ssot:** docs/skill-field-contract-design.md → "### 3.6 F6 — Voice" (imperative + no-hedging; role-noun at a dispatch boundary; + the §3.6 references reader-based extension and §1 references-scope note)

### C2-15 — design-docs-self-standing
- **check:** A Tier-A doc (`docs/*-design.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`) states VeriPower's conventions on their own terms, with no coupling to anything outside the repo: no rule grounded in "aligns with <external project>" / "<external project> does X" instead of on its own merits, and no path or file belonging to another repo. The in-repo `docs/superpowers/` working directory is a local path, not external coupling. (The runtime-content counterpart is C2-04.)
- **signal:** a Tier-A doc grounding a convention in an external project ("aligns with superpowers", "superpowers does X") or citing an out-of-repo file / path; NOT a mere reference to the in-repo `docs/superpowers/` directory.
- **severity:** should-fix
- **applies-to:** docs
- **ssot:** —
- **provenance:** owner policy — the design docs are VeriPower's own SSoT, so a rule contingent on an external project is not self-standing (no in-repo SSoT).

## Class 3 — Verification & epistemic discipline

### C3-01 — claims-are-grep-backed
- **check:** Every factual claim the change makes about the codebase (commit message, comments, docs) is backed by current ground truth — a "shared"/"used-everywhere" claim is backed by an actual consumer grep, a cited file:line / symbol / section anchor resolves, and a stated count matches what the diff changed.
- **signal:** a "shared infra" / "all consumers do X" claim whose §2 consumer-grep returns no citer; a file:line / symbol / section anchor in the change's text that does not resolve; a numeric count the diff's own content contradicts.
- **severity:** consider
- **applies-to:** any
- **ssot:** —
- **provenance:** owner review discipline (grep-before-sharing-claim) — pure epistemic lesson.

### C3-02 — re-verify-before-done
- **check:** A change's "done / fixed / all-tests-pass / verified" claim is backed by evidence in the change itself (the command and its output, a failing-then-passing test, the resolved reference) — not asserted from intent.
- **signal:** a "done" / "all tests pass" / "fixed X" / "verified" claim in the commit message or PR text with no accompanying evidence (no command output, no test name, no diff demonstrating the fix); a success claim the change's own content contradicts.
- **severity:** consider
- **applies-to:** any
- **ssot:** —
- **provenance:** owner review discipline (re-verify before declaring done) — pure epistemic lesson.

### C3-03 — verify-optimization-vs-confounds
- **check:** A claimed optimization (token/perf/size win) isolates the change from confounds — the baseline is stated, the metric measures THIS change's mechanism, and the mechanism is shown to actually engage (presence of a feature ≠ benefit).
- **signal:** a "saves N tokens" / "Y% faster" claim with no baseline; a metric that doesn't isolate the changed pillar; "added feature Z" presented as if its mere presence proves the win.
- **severity:** consider
- **applies-to:** any
- **ssot:** —
- **provenance:** owner review discipline (verify optimization against confounds) — pure epistemic lesson.
