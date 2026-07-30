# Contributing to VeriPower

VeriPower is a stage-gated, event-sourced agent pipeline delivered as a Claude Code plugin. This guide covers the core contribution workflows. For architectural background, read [ARCHITECTURE.md](ARCHITECTURE.md) first.

## Adding or modifying a stage skill

A stage skill's job is to "write `result.json` correctly." DAG routing and state transitions are NOT a stage skill's responsibility — those belong to the Orchestrator and the kernel (`kernel.py`).

Checklist for a new stage skill:

1. `skills/<stage-skill>/SKILL.md` — skill description + instructions. It must be **self-sufficient** — carry every mechanism, gate sequence, and threshold inline, since the plugin end-user has the `SKILL.md` but not veripower's `CLAUDE.md` (the full rule is the §Scope note under [Bulletproofing a skill](#bulletproofing-a-skill-red-green-refactor)). Frontmatter carries only `name` and `description` — no `allowed-tools`; subagent behavior is bound by the dispatch-time prose forbidden-actions list, not tool gating (see [ARCHITECTURE.md §6](ARCHITECTURE.md#6-subagent-contracts)).
2. If needed, `skills/<stage-skill>/references/` — tool manuals, checklists, prompt fragments.
3. If the stage is a new rule (not a replacement of an existing one), add a `Rule` to `framework/scripts/rules.py:RULES` — declaring its `skill`, `execution`, `workdir_root`, and `inputs` / `outputs` artifact selectors (the producer→consumer dependency graph is *derived* from those selectors — there is no separate DAG to edit), plus `proof` and `oracle`. Register its name in `FORWARD_PRIORITY` (and in `ADVISORY_ORDER` only if it needs a non-data sequencing edge). `rules.py` is the SSoT — see the Cross-module SSoT identity note under Coding Conventions. Add unit tests (code-behavior); put any new cross-artifact sync/invariant check in `tests/contracts/`.
4. Add scenario tests under `tests/scenarios/<stage>/` — bulletproof them RED-first via the subagent ritual (see **Bulletproofing a skill**).
5. Update `skills/design-flow/SKILL.md` if the new stage introduces new scheduling semantics.

## Modifying the kernel

The kernel is the deterministic core: `kernel.py` (the CLI and sole writer of `events.jsonl`), `schedule.py` (the `decide` scheduler), `rules.py` (the rule registry), and `facts.py` (event-log I/O + the freshness queries). Changes require unit tests.

Rules:
- **Every scheduling decision lives in `schedule.py`, never in the Orchestrator or a skill.** "If upstream is X, start Y" is a decision — it is computed by `kernel.py decide`; the Orchestrator only executes the one action it returns. Rework-target selection is not a computation at all: the failing envelope names its own `fix_owner` and `schedule.py` checks that naming against the derived input closure. The Orchestrator's only judgment channel is the ask-gated `pin` / `reopen` / human `diagnose` proposals — nothing else. It authors no per-dispatch content: at dispatch time every fact it could state is already a file the target reads, so it passes coordinates and the kernel resolves them into `dispatch.json`.
- **The event log is the only durable state.** A state change is an append to `events.jsonl` via `facts.append_event`, reachable only through `kernel.py` (the sole writer). There is no `task.json` and no status snapshot to keep in sync — per-stage status, freshness, and in-flight are *derived* on demand from the log + disk (`facts.projection` / `proof_valid` / `input_available`). Never add a stored status or freshness field.
- Verb return values are Orchestrator prompt material — new fields need a clear consumer.
- Unit tests live under `tests/unit/`: `test_kernel_cli.py` (verbs), `test_schedule.py` (decide), `test_rules.py` (registry + derived graph), `test_facts_*.py` (events / fingerprints / freshness), Cover happy path + error branches.

## Validating new structured outputs

Which validation regime a new structured output needs depends on its class: kernel-enforced schema validation for verdict outputs ([ARCHITECTURE.md §4.7](ARCHITECTURE.md#47-result-envelope-and-schema-validation)), or a producer self-gate for advisory artifacts. The contributor obligation per class:

- **Verdict output** (`result.json`, event payloads): do not add a field without a schema update **and** a coverage test (`test_event_schemas.py` for an event field, the stage's `test_<stage>_result.py` for a `result.json` field). The kernel validates events at append time and `result.json` at reap, so an unschema'd field corrupts the deterministic core.
- **Descriptive/advisory artifact** (e.g., triage ANALYSIS, verification scaffold): ship a `scripts/validate_*.py` producer self-gate (pattern: `skills/simulation-triage/scripts/simtriage/__main__.py`, `skills/simulation-plan/scripts/simplan/__main__.py`); the skill fixes-and-retries before emitting. Do **not** add a `kernel.py` verb for advisory validation — the kernel never validates the artifact's content.

## Testing

- `tests/unit/` — pure-Python code-behavior tests (call a framework function, assert output). `tests/contracts/` — deterministic artifact sync/invariant lints (read declarations & compare; run no code). Run `pytest tests/unit/ tests/contracts/` for the fast loop when changing the kernel (`kernel.py` / `schedule.py` / `rules.py` / `facts.py`), schemas, or any cross-artifact contract.
- `tests/scenarios/` — skill-level discipline tests under pressure. No EDA tools; uses Claude (Opus) as the system under test, run via a **clean-isolation `claude -p` subprocess** (`tests/scenarios/scenario-run.sh`) — see **Bulletproofing a skill** below.
- **CI** (`.github/workflows/ci.yml`) is the enforcement net for the gates you run locally: `pytest` on Python 3.10/3.11/3.12, and the `pre-commit` lint gate ([Coding Conventions](#coding-conventions)) on 3.12 — on every push and PR; PRs must be green to merge. Keep running both locally for fast feedback; CI is the net, not the loop. `tests/scenarios/` is deliberately **not** in CI: it drives a live `claude -p` subprocess (non-deterministic, needs model access) and stays a manual gate.

## Bulletproofing a skill (RED-GREEN-REFACTOR)

Testing a VeriPower skill **is** TDD applied to the skill document. The test *subject* is a fresh, isolated `claude -p` subprocess — **not** an in-session subagent. This matters: an in-session subagent inherits the project `CLAUDE.md`, **the developer's auto-memory, and repo file-access**, all of which pre-encode the invariants under test and contaminate the RED baseline — even a tools-off subagent stays compliant, carrying the auto-memory's invariant notes and reading `SKILL.md` straight from disk. The runner `tests/scenarios/scenario-run.sh` gives a clean baseline — a temp workdir (no developer auto-memory, no skill auto-load), `--allowedTools ""` (no file reads), and only the context it injects. Both RED and GREEN run on **Opus** (= production), so teeth are judged against the model that ships.

**RED-first acceptance gate:** keep a scenario only if it *fails RED and passes GREEN*. A scenario the agent gets right on RED is toothless (bare Opus already complies) — discard or re-aim it.

**Per scenario** (the runner does RED/GREEN; you judge + REFACTOR):
1. **RED** — `scenario-run.sh --skill <s> --scenario <id> --mode red` injects **nothing** — bare Opus, no project `CLAUDE.md`, no `SKILL.md` (baseline + isolation caveat: `tests/scenarios/README.md`). Read the printed `DECISION:`/`ACTION:` tag. **Expected: it fails** (violating option / proceeds when it should block).
2. **GREEN** — `--mode green` injects `skills/<s>/SKILL.md` **alone** — exactly what a plugin end-user receives. **Expected: it complies.**
3. **REFACTOR (on GREEN failure)** — edit the skill: an explicit negation in the rule + a rationalization-table row (the agent's **verbatim** excuse → reality) + a Red-Flags entry + a `description` symptom. Then **meta-test** (a follow-up `claude -p` with the transcript, or in-session reasoning — meta-testing is not a baseline, so contamination is harmless): "you read the skill and still chose X; how should it have been written to make the compliant option unambiguous?" Apply the answer; re-run GREEN until it passes.
4. **Record provenance** — stamp the scenario frontmatter `baseline: fail` / `green: pass` / `activated: <date>` / `model: opus`. For a borderline tag, run 2–3 times and take the majority.

**Scope (the SKILL.md-self-sufficiency rule):** target what each skill's **`SKILL.md` must carry on its own** — its mechanisms, exact gate sequences, thresholds — since the plugin end-user has the `SKILL.md` but not veripower's `CLAUDE.md`. Skills whose discipline **bare Opus already holds unaided** get few or zero scenarios; never manufacture pressure — an empty per-skill corpus is an honest outcome, not a gap. Baseline + isolation caveat and live corpus status: [`tests/scenarios/README.md`](tests/scenarios/README.md).

**Scenario types:** `pressure` (`DECISION: A/B/C`) and `missing-info` (`ACTION: PROCEED/BLOCKED`) self-report a tag the runner extracts. `open` (answer key in `## Expected Behavior` / `## Anti-Pattern`) has no tag — human/main-agent judgment only.

**Regression (after editing a skill):** re-run that skill's scenarios `--mode green`. A previously-passing scenario that now fails means the edit reopened a hole — fix before merging.

## Documentation

- **Script contract sync (mandatory).** Each SKILL.md is the *complete* runtime contract for the scripts it invokes — agents run them per its documented command lines rather than reading their source. So any change to a directly-invoked script's CLI flags, exit codes, or output shape MUST update the invoking SKILL.md (and the script's `--help` text) in the same commit; a new script MUST be classified at introduction (directly-invoked: document the full command line + failure protocol; bootstrap-/make-internal or import-only: one line marking it internal). Silent drift breaks the black-box rule for every downstream run.
- **ARCHITECTURE.md no-restatement rule.** State each cross-cutting invariant **once** — either at a single home section (every other mention cross-refs it), or split across a rationale sentence + a `> **Contract:**` box that each state only their half (the *why* vs. the verifiable form). A *localized* contract — a per-stage `result.json` field, a CLI flag — is **never restated** here; link to its SSoT (the owning `result.schema.json` description / `kernel.py --help`) instead. New architectural content picks one home before it lands; if you find yourself writing a fact this document already states, cross-reference it rather than rephrasing it.
- **User/contributor-facing content** (architecture, contribution norms) — lives at the repo root: [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md), this file.
- **Brainstorming, design proposals, review records** — under `docs/superpowers/`. These are uncommitted by convention (see `.gitignore`).

## Language posture

VeriPower content lives on two surfaces: Surface 1 (runtime-LLM-consumed; English-only) and Surface 2 (user-data; bilingual, follows user language). For the full rule and the boundary criterion, see [`docs/language-posture-design.md`](docs/language-posture-design.md). When writing skill content, use the established workflow vocabulary already present in `skills/<name>/SKILL.md` and `skills/<name>/references/*.md` as the source of truth.

## Commit messages

One inclusion test decides what goes in: **write only what a reader can't recover from a more authoritative source.** The diff already records *what changed*; CI records *whether it passes*. A message owns only what neither does:

- **Subject** — imperative, intent not mechanism, with a `type:` prefix (`ci:`, `docs:`, `fix:`, `style:`, …). Self-evident commits can stop here.
- **Body** (when warranted) — the *why*: problem + root cause (cause only when non-obvious). No file:line evidence (the diff has it); length scales with the change.
- **Verification** — only for checks CI does *not* run: manual bring-up, a local EDA flow, a reproduced bug. Don't write "pytest passes" — CI is the authoritative pass/fail record.
- **Trailers** — `Co-authored-by:`, issue refs.

## Pull requests

A PR adds one authoritative source on top of the commits: the commit list itself. So the same inclusion test gains a clause — **write only what the diff, CI, *and the individual commit messages* don't already give.** What's left is PR-unique: the umbrella *why* and reviewer guidance.

- **Title** — like a commit subject (imperative, intent, `type:` prefix), but the *umbrella* intent of the whole PR, not a copy of one commit. If the repo squash-merges, this becomes the merge commit's subject — keep it convention-clean.
- **Description** — the umbrella why (what these commits deliver together) plus reviewer guidance: where to start, what's risky, what's deliberately out of scope, what to verify by hand. Link issues with `Closes #N`. Don't re-list files (the diff has them), don't say "tests pass" (CI does), don't re-narrate each commit (the commit list does).

One PR, one logical change; length scales with the change. The `.github/PULL_REQUEST_TEMPLATE.md` prefills this shape.

### Merge strategy

Rebase and merge — keeps history linear and preserves each commit's message. Squash only a PR of WIP/fixup commits not worth keeping apart. Avoid merge commits (they own nothing the commits / PR / CI don't already).

## Coding Conventions

Enforced by `pre-commit` (`ruff` + `shellcheck` + `shfmt`); run `pre-commit run --all-files` (or `pre-commit install` once for the per-commit hook). Config: `ruff.toml`, `.shellcheckrc`, `.pre-commit-config.yaml`.

**Python**
- Naming: `snake_case` functions/vars, `UPPER_SNAKE` constants, `_private` prefix. No `camelCase`.
- Formatting: `ruff format` (88 cols); imports sorted by ruff `I`. f-strings (not `%`/`.format`, except dict-unpack `"{x}".format(**d)`). `pathlib.Path` over `os.path`.
- A script that is directly runnable (`if __name__ == "__main__"`) starts with `#!/usr/bin/env python3`; import-only library modules do not.
- Exit via `sys.exit(...)` — never `raise SystemExit(...)`. Pass an int code, or a `"<script>: message"` string for fail-fast (Python prints it to stderr and exits 1; see the `_fail()` helper in `spec/constraints.py`). Use `print(..., file=sys.stderr)` for diagnostics that aren't the exit message itself. Exit codes: 0 ok, 1 runtime failure, 2 usage.
- New scripts are fully type-annotated. (Legacy partial annotations are not retrofitted.)
- JSON I/O: `json.dumps(..., ensure_ascii=False)`; `indent=2` for files written to disk; compact (no indent) only for single-line stdout payloads consumed by a caller.

**Shell**
- `#!/usr/bin/env bash` + `set -euo pipefail` for executable scripts. Sourced POSIX files (`env.sh`) carry `# shellcheck shell=sh`.
- Tabs (`shfmt -i 0`). `[[ ]]` tests (not `[ ]`). `UPPER_CASE` globals, `local` lowercase. Quote expansions (`"$VAR"`); brace where needed (`${VAR}`).
- Errors to stderr prefixed `<script>: ...` `>&2`. Exit codes: 2 usage, 1 runtime, 0 ok.

**EDA templates** — three placeholder conventions:
- `MY_*` — substituted by the bootstrap shell via `sed` (default for shell/TCL/SDC templates).
- `{{VAR}}` — substituted by Python at scaffold-build time (the simulation `render-scaffold` verb for the simulation scaffold, `emit_power_tests.py` for the power scaffold).
- `FILL_IN_*` — a sentinel for a value the human must supply (e.g. `FILL_IN_LIB_DB_PATH`); the bootstrap substitutes it only when it can resolve a value, and the tool script fail-closes if the sentinel survives.

**Cross-module SSoT identity** — import shared SSoT modules the bare way (`import rules` after putting `framework/scripts` on `sys.path`, as `kernel.py` / `schedule.py` / `facts.py` and the tests all do), never via the package path (`framework.scripts.rules`); the latter creates a second module object and breaks the `kernel.rules is schedule.rules` identity (the dup-module bug class). Do not add re-exports for test convenience; tests read framework constants from their real home module. Guarded by `tests/unit/test_kernel_cli.py::test_bare_import_single_module_identity`.

**File naming** — each stage's Tier-1 scripts live in one package `skills/<stage>/scripts/<pkg>/` (`<pkg>` = the short stage tool name, no hyphens, e.g. `lint-cdc`→`lintcdc`): a thin `__main__.py` argparse entry dispatches verb subcommands to focused `<verb>.py` / `_<lib>.py` modules (no god-file). Verbs follow the shared vocabulary (`bootstrap` / `finalize` / `derive-*` / `materialize-*` / `render-*` / `check-*` / `validate-review`). `validate-review` is not a default: specification dropped it when its reviewers began writing their own per-child files, because the verb was validating a record the main thread had just re-typed, and the verdict it computed was then checked against that same thread's own `--status`. Add it only where a review record has a reader other than the party being checked. Framework libraries keep domain-noun names (`rules.py`, `store.py`); kebab-case skill directories.

## Further reading

- **EDA tool environment** — PATH, `LIB_DB`, `UVM_HOME`, `/bin/sh→bash`, optional `VCS_CC`: [docs/eda-env.md](docs/eda-env.md).
- **Repository layout** — plugin tree: [README.md § Repository layout](README.md#repository-layout); per-module workspace: [ARCHITECTURE.md §7](ARCHITECTURE.md#7-workspace-layout).
