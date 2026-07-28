# Rule input/output necessity — implementation-time second pass

> Merge-gate review required by the incremental-kernel design §2 ("必要性判据 / 核验方法学").
> The spec ran this once at the spec layer; this is the **implementation-time re-run against
> the current `framework/scripts/rules.py`**, recorded so the gate is auditable (closes G5).

## Method (the three relations)

Necessity is decided by **proof semantics**, not by "is it referenced somewhere":

- An **input** is necessary iff the rule's `verdict` depends on it (changing it could flip or
  invalidate the proof).
- An **output** is necessary iff it is proof evidence, a downstream input, or a contract
  deliverable.

Three relations must hold for `rules.py`:

1. `read ⊆ declared` — everything a rule's scripts read is a declared input. **Mechanically
   anchored** — a stray upstream `status=pass` gate-read is caught by `tests/contracts/
   test_no_gate_reads.py`; declared-input reachability by `tests/unit/test_rules.py`.
2. `declared` all trace to a producer or `PIPELINE_INPUTS` — **mechanically tested**
   (`test_rules.py::test_every_input_traces_to_a_producer_or_pipeline_input`, acyclicity too).
3. **`proof-dependency closure ⊆ declared`** — every verdict-dependency is declared (or has a
   named reaching-path / identity classification). **Semantically complete, mechanically
   undecidable** — this per-rule pass IS relation 3.

Pass criterion per rule: *every verdict-dependency is either in the declared set, or has a
named reaching-path, or is an identity/coordinate class (frozen operator external / tool
identity / coordinate absorbed by another tracked input) that legitimately is not tracked.*

## Per-rule pass

| Rule | oracle / verdict | verdict-dependencies → declared? / reaching-path / identity |
|---|---|---|
| **specification** | `spec-review` (proposed) — faithfulness + conformance + coverage vs brainstorm | `brainstorm.md` ✓ declared. Self-produced `design.md`/`manifest.json`/`<child>.md` — covered by output binding (proof cond 4). Design/review templates = skill identity. **PASS.** |
| **simulation-plan** | `plan-review` (proposed) — testpoint coverage/adequacy vs spec | `design.md` / `manifest.json` / `*.md` (children) / the authored sidecars ✓ declared. No RTL edge (windows narrow-edge ①: whitebox monitor hierarchy is derived at the sim stage, plan carries abstract names). **PASS.** |
| **rtl-design** | `semantic-review` (proposed) — per-child faithfulness | `design.md` / `manifest.json` / `*.md` ✓ declared. **NOT** `constraints/*` — the constraints are a deterministic derivation of `design.md`, binding them = same-source double-binding (only net effect: template edits falsely rebuild RTL). PPA target arrives via `--directive` (params), not an input. coding-rules = skill identity. **PASS.** |
| **lint-cdc** | `spyglass-ruleset` (tool) — CDC/lint clean | RTL fileset (`*.v`, `filelist.txt`), `README.md`, `sgdc_seed` (`constraints/*.sgdc`), `waiver.tcl` (in∩out) ✓ declared. Child-doc CDC intent reaches via rtl-design → RTL/README (both declared). SpyGlass ruleset = oracle identity. The §1.6 clock-group Relationship IS covered: `derive-constraints` emits `clock -domain` into the SGDC seed (`_sgdc_clock_domains`), so a clock-relationship change re-derives the seed and re-verifies lint. (SpyGlass_vL-2016.06 already flags undeclared crossings by default — the earlier F1 "silent-miss" framing was empirically reversed; the `-domain` emission makes the sync/async relationship explicit and prevents spurious flags, not changes the verdict.) **PASS.** |
| **synthesis** | `dc-shell` (tool) — synthesis + PPA acceptance | RTL fileset, `README.md` (SDC exception notes), `constraints/*.sdc`, `ppa.json` ✓ declared. lint/rtl envelope diff = scope optimization, not a verdict-dep. `LIB_DB` = tool identity (§1.2, not tracked). **PASS.** |
| **timing-analysis** | `pt-shell` (tool) — timing closure | `*_syn.v` + `*_syn.sdc` (synthesis outputs) ✓ declared. PPA targets are NOT a dep (fixed zero-slack judge — reverified by counterfactual). `LIB_DB` = tool identity. **PASS.** |
| **simulation** | `tb-refmodel` (proposed) — TB pass vs refmodel | RTL fileset, `verification-plan.md`, `scaffold-specification.json` ✓ declared. **README removed this pass (D6/G4):** simulation's only README use was top inference, now read from `manifest.module` — a **coordinate lookup** whose freshness is absorbed by the tracked RTL fileset (§2⑦: a real top change necessarily changes RTL bytes), so the manifest read is NOT a tracked input, and README prose was never a verdict-dependency (binding it only caused README-only edits to falsely invalidate). ROM/whitebox golden = frozen identity. coverage threshold ∈ skill `defaults.yaml` = skill identity. freeze baseline = self cache. **PASS (over-declaration removed).** |
| **power-analysis** | `pt-shell` (tool) — power + PPA acceptance | `*_syn.{v,sdc,sdf}`, TB env (`env.sh`/`filelist.f`/`rtl_filelist.f`/`tb/uvm/*`), `scaffold-specification.json`, `ppa.json` ✓ declared. run-dir hex images = frozen operator externals. `LIB_V`/`LIB_DB`/`UVM_HOME` = tool identity. **PASS.** |
| **simulation-triage** | none (`proof=None`) | No proof → closure obligation is empty. Analysis quality is an oracle-side concern, carried by the disposition reliability gate + human diagnosis (§3.4). **N/A.** |

## Findings this pass surfaced

- **Over-declaration (fixed):** `simulation` declared `README.md` (`rtl_doc`) yet README prose
  is not a sim verdict-dependency — its only use was top inference, migrated to
  `manifest.module`; the input was dropped (D6/G4). README-only edits no longer falsely
  invalidate the simulation proof.
- **§1.6 coverage (verified present):** `lint-cdc`'s SGDC seed DOES cover the §1.6
  clock-group Relationship — `derive-constraints` emits `clock -domain` (`_sgdc_clock_domains`),
  landed and tested (`test_sgdc_emits_async_clock_groups`) on the F1 base. The earlier F1
  "silent-miss" severity was empirically reversed on SpyGlass_vL-2016.06 (it flags undeclared
  crossings by default); the emission makes the relationship explicit, not the verdict.
- **Never-ran availability (fixed):** an input whose producer never ran is now `unavailable`
  (matches the §2 availability definition), closing a manual-dispatch vacuous-proof hole (F7).
- **Re-derived after `frontend-signoff` left the registry — no delta.** A pure sink: no rule
  declared its outputs as an input, so it sat in no other rule's `input_closure` and its
  removal cannot move any surviving rule's necessary-input set. Every row above re-checked.
- Relations 1 and 2 are held by the mechanical tests cited above; this document is the
  auditable record for relation 3. Re-run it whenever a `Rule` in `rules.py` gains/loses an
  input or output selector — or is added or removed.
