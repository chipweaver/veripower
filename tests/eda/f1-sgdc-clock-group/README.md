# F1 SpyGlass multi-clock CDC regression

One-time, **manually-run** (EDA-gated, not in `pytest`, no SpyGlass in CI) regression that
pins `SpyGlass_vL-2016.06`'s default multi-clock CDC semantics against a minimal 2-clock
design, and empirically checks the F1 claim behind Task 1's fix (`generate_sgdc` now emits
an async clock declaration mirroring the SDC).

## How to run

From `/home/mhc/veripower` (must run under `WORKSPACE_ROOT` = `/home/mhc`):

```bash
bash tests/eda/f1-sgdc-clock-group/run.sh
```

Runs SpyGlass CDC (`cdc/cdc_setup` → `cdc/cdc_setup_check` → `cdc/cdc_verify_struct`) on
`rtl/cdc_smoke.v` twice — once with `scripts/nogroups.sgdc`, once with
`scripts/groups.sgdc` — and leaves `cdc-violations.{nogroups,groups}.json` (gitignored;
this file records the summaries).

## DUT

`cdc_smoke`: register `a` (clk domain) sampled by a single, unsynchronized flop `q` (clk2
domain) — a genuine async crossing with no synchronizer. `clk` = 10.0 ns, `clk2` = 20.0 ns.

## Environment notes (two workarounds, neither changes the CDC question under test)

Both were root-caused via reproducible A/B testing (relative-vs-absolute path, single-file
vs multi-file sourcelists, isolated on a real production module (`microgpt_core`) as a
known-good control) before being applied — see the run.sh comments for the mechanism.

1. **`collect_report.py` root resolution.** It resolves its output root from its own file
   location (`Path(__file__).resolve().parent.parent`), assuming co-located deployment (as
   the lint-cdc skill does: script copied into `runs/<N>/scripts/`). Invoked here by
   absolute cross-directory path, it resolves to `skills/lint-cdc/templates/` instead of
   this fixture, and exits 1 `FAIL=missing`. Worked around by running a local copy
   (`scripts/collect_report.py`, gitignored) so `__file__` resolves correctly; deleted
   after each variant.

2. **SpyGlass_vL-2016.06 relative-sourcelist bug.** `open_project` fatals with a bare
   `found errors in project file` (no further detail available — confirmed via `catch`,
   `errorInfo`, and the compiled-proc call stack, which repeats the same generic message)
   when `scripts/filelist.txt`'s sourcelist entry is a **relative** path for a small/
   single-file design. Confirmed reproducible and content-independent: identical
   single-file projects (with or without an SGDC, with or without `set_option`s matching
   the working lint-cdc template, with the RTL module ranging 18–315 lines) fail 9/9 with
   a relative sourcelist path and pass 6/6 with an absolute one; a real multi-file module
   list (`microgpt_core`, 13 files) passes regardless. Worked around by having `run.sh`
   rewrite `scripts/filelist.txt` to an absolute path for the run and restore the
   committed relative-path content on exit (bash `trap`, so it restores even on error) —
   the tracked file's content is unaffected.

## SGDC fallback triggered: `set_clock_groups` is not valid SGDC

The plan's per-spec directive form is `set_clock_groups -asynchronous -group [get_clocks
{…}] -group [get_clocks <c>]` (a standard **SDC** construct). SpyGlass's SGDC parser
rejects it outright:

```
[1]  SGDCSTX_002  SGDCSTX_002  Syntax  scripts/constraints.sgdc  4  10
     Unknown SGDC command 'set_clock_groups'
```

This is the brief's anticipated fallback trigger (an SGDC_* setup error, not a CDC
violation). The working SGDC-native form (per
`SpyGlass_ConstraintsMethodology_GuideWare2.0_UserGuide.pdf`, confirmed by direct test) is
`clock -name <n> ... -domain <D>`: all `primary`/`synchronous-related` clocks share one
domain name, each `async` clock gets its own distinct domain. `groups.sgdc` was corrected
to:

```
clock -name clk  -period 10.0 -edge {0 5.0}  -domain sync
clock -name clk2 -period 20.0 -edge {0 10.0} -domain clk2
```

**Task 1 correction (binding constraint, since the fallback triggered):** `_async_clock_groups`
in `skills/specification/scripts/spec/constraints.py` stays as-is (SDC still uses valid
`set_clock_groups`). A new `_sgdc_clock_domains` helper computes the same
sync-group/async-singleton partition and `generate_sgdc` now emits `-domain <D>` inline on
each `clock -name` line instead of a trailing `set_clock_groups` line. `_self_check`'s
divergence backstop now compares `"set_clock_groups" in sdc` against `"-domain" in sgdc`
(same underlying data, different native syntax per format). `sgdc-template.md` and
`tests/unit/test_spec_constraints.py` updated to match;
`python3 -m pytest tests/unit/test_spec_constraints.py -v` → **19 passed**; full
`tests/unit/` → **967 passed**.

## Result: both variants are identical — the "vacuous pass" half of F1 does not reproduce here

```
=== nogroups: cdc-violations.json ===
{
  "counts":  {"error": 1, "warning": 1, "info": 15},
  "totals":  {"generated": 17, "waived": 0, "reported": 17, "overlimit": 0}
}
violations[error]:
  Ac_unsync01  Unsynchronized Crossing: destination flop cdc_smoke.q, clocked by
  cdc_smoke.clk2, source flop cdc_smoke.a, clocked by cdc_smoke.clk.
  Reason: Qualifier not found [Total Sources: 1 (Number of source domains: 1)]

=== groups: cdc-violations.json ===
{
  "counts":  {"error": 1, "warning": 1, "info": 15},
  "totals":  {"generated": 17, "waived": 0, "reported": 17, "overlimit": 0}
}
violations[error]:
  Ac_unsync01  Unsynchronized Crossing: destination flop cdc_smoke.q, clocked by
  cdc_smoke.clk2, source flop cdc_smoke.a, clocked by cdc_smoke.clk.
  Reason: Qualifier not found [Total Sources: 1 (Number of source domains: 1)]
```

**Confirmed rule id: `Ac_unsync01`** (policy `clock-reset`, goal `cdc/cdc_verify_struct`,
severity `error`) — this is the rule id C5's failure-category table should record for an
unsynchronized single-flop CDC crossing.

**The expected delta did not appear.** The brief's hypothesis was: `nogroups` → CDC clean
(vacuous, the bug); `groups` → CDC flags the `a→q` crossing (the fix). Empirically, on
`SpyGlass_vL-2016.06`, **`nogroups` already flags `Ac_unsync01`** — identically to
`groups`, down to the exact counts and message. Root cause, confirmed via
`cdc/cdc_setup_check`'s `Propagate_Clocks` messages:

```
nogroups: clock(s) 'cdc_smoke.clk'  of domain 'clk'   propagated   (no -domain given)
          clock(s) 'cdc_smoke.clk2' of domain 'clk2'  propagated   (no -domain given)
groups:   clock(s) 'cdc_smoke.clk'  of domain 'sync'  propagated   (-domain sync)
          clock(s) 'cdc_smoke.clk2' of domain 'clk2'  propagated   (-domain clk2)
```

SpyGlass assigns each separately-`clock -name`d signal its **own default domain (its own
name)** whether or not `-domain`/`-group` is declared. `cdc/cdc_verify_struct`'s
`Ac_unsync01` check flags a missing synchronizer between any two *different* domains,
regardless of whether that difference is explicit or default — so for two independently
named clocks, an explicit `-domain` assignment is a relabeling of an already-separate
default, not new information the structural checker needed. (Symmetrically, `-domain`'s
real effect is the opposite direction: it is how you'd **merge** two independently-named
signals into the *same* domain, e.g. a clock renamed across a block boundary, suppressing a
false-positive crossing — not how you'd get an unrelated pair flagged, since unrelated pairs
are flagged by default already.)

**Judgment:** the fix (Task 1: SDC and SGDC must not diverge on the async declaration) is
still correct and worth keeping — it is the SGDC-native way to state the intended clock
relationship accurately (and it's a genuine defect that the generator produced diverging
files at all — a downstream consumer diffing SDC against SGDC would rightly flag that). But
**this specific regression does not demonstrate a vacuous CDC pass being fixed** by adding
it: on this tool version, for this crossing shape (two independently-named non-generated
clocks, no synchronizer), `cdc/cdc_verify_struct` already flags `Ac_unsync01` with no SGDC
group/domain declaration at all. Whoever owns the kernel plan's Task C4/C5 should treat "F1
landed" as: Task 1's generator fix is real and tested (unit-level); Task 2's tool-level
claim that omitting the declaration causes a *vacuous* CDC pass is **not reproduced** by
this minimal fixture — it may hold for a different check (not `cdc_verify_struct`), a
different clock-relationship shape, or the SDC/STA side (`set_clock_groups` is meaningful
to STA tools regardless of SpyGlass CDC), none of which this regression tests.
