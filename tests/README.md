# VeriPower `tests/`

Three test buckets, each answering exactly **one** question, plus a shared-helper module. Use
this file to decide where a new test goes.

> **The unit of classification is the test *function*, not the file.** A file may legitimately
> split across buckets; route each function by the question it answers.

## Decision table

| Bucket | The one question it answers | What lives here | Executes code? |
|---|---|---|---|
| **`unit/`** | Does framework **code** behave? | a test that **calls** a `framework/scripts/` or `skills/*/scripts/` function and asserts its output / side-effects | yes — Python |
| **`contracts/`** | Do framework **artifacts** hold invariants & stay in sync? | a deterministic lint that **reads declarations and compares** them — incl. cross-refs where one side is a SKILL.md token | **no** |
| **`scenarios/`** | Does the **agent** decide right under pressure? | tools-off LLM pressure tests, rebuilt RED-first and run via a **clean-isolation `claude -p` subprocess** (`scenarios/scenario-run.sh`); closed-form self-report a verdict tag, `open` ones human/meta-test judged (see `scenarios/README.md`) | n/a — LLM |

**Not a bucket →** `replay/` is a **measurement harness**, not an assertion set: it replays a
real run's event log against `decide` and reports how many decision points match what the real
Orchestrator did. Nothing fails; a human reads the number. See `replay/README.md`.

**Not a test →** single-artifact **prose / authoring / structure quality** is *not* asserted by
any script here. It is reviewed by the **`veripower-review`** skill. If
your check is "the wording / sections / style of one document are right," it does not belong in
`tests/` at all.

**Mnemonic:** unit tests *code* · contracts tests *artifact sync/invariants* · scenarios tests
*agent judgment* · veripower-review judges *prose quality*.

## Routing the two hard cases

These are the decisions the bucket names alone don't settle — get them right and everything
else follows.

### 1. A check that reads a SKILL.md (or any doc): sync → `contracts/`, prose → **not a test**

This is the most error-prone call. Decide by **how many artifacts the assertion relates**:

- **Two (or artifact↔disk/code) → `contracts/`.** It's a binary cross-artifact sync/invariant.
  Examples (live): `contracts/test_skill_path_references.py` (every backtick path in a SKILL.md
  `exists()` on disk); `contracts/test_schema_skill_reciprocity.py` (each schema-required field is
  named in the SKILL.md, both directions); `contracts/test_cross_stage_contracts.py`.
- **One — just inspecting a single document's text → NOT a test; goes to `veripower-review`.**
  "This string/section appears", "the wording is X", "english-only", "frontmatter shape". A check
  that merely asserts a script's *filename string* appears in a SKILL.md is prose-presence, not a
  sync (it doesn't verify the file exists — that's the `contracts/` version above). Authoring
  quality is judgment about one artifact → `veripower-review`, never a deterministic script.

> The single discriminator: **does the assertion compare two things, or inspect one thing's
> prose?** Two → `contracts/`. One → `veripower-review`.

### 2. A test that *calls code* AND asserts a cross-artifact property → `unit/`

If the test **executes** framework code (runs the spec `derive-constraints` verb, calls `compute_purity`),
it is `unit/` — even when it also asserts a cross-artifact result. You are testing the code's
behavior. `contracts/` is reserved for checks that run **no** code (pure read-and-compare of
declarations). When a check could be written either way, prefer testing the **shipped producer**
in `unit/` over re-deriving its logic in a standalone lint.

## Shared infrastructure (not buckets)

- **`_skills_sot.py`** — shared test helpers/values: `PLUGIN_ROOT`, `load_stage_schema(stage)`,
  and `SKILL_DIRS` (**derived live**
  from `skills/*/SKILL.md` — the filesystem is the source of truth, not a hand-maintained list).
  Importable from `unit/` and `contracts/` via `pytest.ini`'s `pythonpath = . tests`
  (`from _skills_sot import …`) — a module, not `conftest.py`, because these are imported by name.
- **Test fixtures** live *inside the bucket that uses them* — e.g. `unit/fixtures/parse_coverage/`
  (URG report samples for `test_parse_coverage`). There is **no** shared
  top-level `fixtures/`: a fixture used by one bucket belongs to that bucket.

## Running

```bash
python3 -m pytest tests/unit/ tests/contracts/   # fast deterministic loop (no EDA tools)
./tests/scenarios/scenario-run.sh --skill <name> --scenario <id> --mode red|green   # one scenario, clean claude -p (needs claude CLI); see CONTRIBUTING.md "Bulletproofing a skill"
```
