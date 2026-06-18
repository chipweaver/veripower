"""Verify the rework-trigger invariant for the dispatcher (state.cmd_dispatch).

Invariant: ``mode == "rework"`` ⟹ ``rework_trigger`` is injected into the
dispatch payload **OR** the canonical workdir already holds prev artifacts
on disk.

Three paths in ``state.py`` produce ``mode == "rework"``:

1. **First-run** (not_started/clean) — mode=forward, trigger=None. Invariant
   holds trivially because mode≠rework.
2. **Explicit rework** (Orchestrator ``cmd_rework``) — mode=rework + trigger is populated.
   Invariant holds because trigger is injected.
3. **Cascade rework** (upstream pass marks downstream stale) — mode=rework +
   trigger=None, but prev artifacts MUST be on canonical disk because cascade
   only stales stages already pass/fail/in_progress (state.py:_compute_cascade
   skips not_started; see state.py:211 et seq.).

These tests lock the invariant so the upcoming "fold mode routing into
trigger-existence + disk-state" refactor (Tasks 2-6 of the 04-29 plan) has a
verified runtime baseline.
"""

from conftest import write_run_result

from framework.scripts.state import (
    _result_path,
    cmd_dispatch,
    cmd_init,
    cmd_reap,
    cmd_rework,
)


def _start_pass_complete(module: str, stage: str) -> int:
    """Dispatch + complete a stage with outcome=pass. Returns the run number."""
    r = cmd_dispatch(module, stage)
    assert r["ok"], f"cmd_dispatch({stage}) failed: {r}"
    run = r["run"]
    write_run_result(module, stage, run)
    res = cmd_reap(module, stage, run=run, outcome="pass")
    assert res.get("action") == "completed" and res.get("result_status") == "pass", (
        f"cmd_reap({stage}, run={run}, pass) failed: {res}"
    )
    return run


# ── tests ─────────────────────────────────────────────────────────────────


def test_cascade_rework_skips_not_started_stages(tmp_path, monkeypatch):
    """First-run (not_started/clean) stages are NOT cascade-stale'd.

    After specification + simulation-plan pass, dispatching rtl-design for the first time must yield
    mode=forward (not rework). _compute_cascade only walks pass/fail/in_progress
    descendants; not_started stages stay untouched. (state.py:_compute_cascade)
    """
    monkeypatch.chdir(tmp_path)

    cmd_init("M1")

    # specification first run, pass
    r = cmd_dispatch("M1", "specification")
    assert r["ok"] and r["mode"] == "forward"
    assert "rework_trigger" not in r
    write_run_result("M1", "specification", r["run"])
    cmd_reap("M1", "specification", run=r["run"], outcome="pass")

    # simulation-plan first run, pass (rtl-design's direct prereq)
    _start_pass_complete("M1", "simulation-plan")

    # rtl-design first dispatch — was not_started while specification/simulation-plan transitioned to
    # pass, so cascade did not touch it; mode must be forward, no trigger.
    r2 = cmd_dispatch("M1", "rtl-design")
    assert r2["ok"]
    assert r2["mode"] == "forward", (
        f"first-time rtl-design after specification+simulation-plan pass should be forward, got {r2['mode']}"
    )
    assert "rework_trigger" not in r2


def test_explicit_rework_has_trigger(tmp_path, monkeypatch):
    """Orchestrator cmd_rework dispatches a target stage with mode=rework + populated trigger.

    After cmd_rework(failed_stage=rtl-design, target_stage=specification), the next cmd_dispatch(specification)
    must inject rework_trigger pointing to the failed stage's canonical result path
    (Design/rtl-design/result.json).
    """
    monkeypatch.chdir(tmp_path)

    cmd_init("M1")

    # specification → simulation-plan → rtl-design first runs (rtl-design's prereq chain).
    _start_pass_complete("M1", "specification")
    _start_pass_complete("M1", "simulation-plan")
    _start_pass_complete("M1", "rtl-design")

    # Orchestrator decides rtl-design needs to be reworked from specification
    rew = cmd_rework(
        "M1",
        failed_stage="rtl-design",
        target_stage="specification",
        reason="manual test rework path",
    )
    assert rew.get("ok", True) is not False, f"cmd_rework failed: {rew}"

    # Re-dispatch specification — must arrive as rework with trigger pointing at rtl-design
    r3 = cmd_dispatch("M1", "specification")
    assert r3["ok"]
    assert r3["mode"] == "rework", f"expected rework, got {r3['mode']}"
    assert "rework_trigger" in r3, (
        f"explicit rework must inject rework_trigger, got keys={list(r3)}"
    )
    assert "rtl-design" in r3["rework_trigger"], (
        f"rework_trigger should point at failed_stage rtl-design, got {r3['rework_trigger']!r}"
    )


def test_cascade_rework_no_trigger_but_prev_artifacts(tmp_path, monkeypatch):
    """Cascade rework: mode=rework + trigger=None; prev artifacts must be on disk.

    Sequence: specification → simulation-plan → rtl-design all pass (canonical Design/rtl-design/result.json
    promoted) → cmd_rework(rtl-design→specification) (stales specification/simulation-plan/rtl-design via cascade) →
    specification re-pass and simulation-plan re-pass restore the chain → cmd_dispatch(rtl-design) yields
    mode=rework (rtl-design is pass/stale from the most recent cascade) WITH NO
    rework_decision targeting rtl-design. Per the invariant, prev artifacts —
    canonical Design/rtl-design/result.json promoted by the first rtl-design run — must
    still be on disk.
    """
    monkeypatch.chdir(tmp_path)

    cmd_init("M1")

    # Initial chain: specification → simulation-plan → rtl-design all pass.
    _start_pass_complete("M1", "specification")
    _start_pass_complete("M1", "simulation-plan")
    _start_pass_complete("M1", "rtl-design")

    canonical_rtl_design_rj = _result_path("M1", "rtl-design")
    assert canonical_rtl_design_rj.exists(), (
        "after rtl-design pass+promote, canonical rtl-design result.json must exist"
    )

    # Orchestrator triggers rework: failed=rtl-design, target=specification.
    # cmd_rework cascades from specification, which stales simulation-plan AND rtl-design (both pass/clean).
    rew = cmd_rework(
        "M1",
        failed_stage="rtl-design",
        target_stage="specification",
        reason="cascade trigger setup",
    )
    assert rew.get("ok", True) is not False, f"cmd_rework failed: {rew}"

    # specification re-runs and passes — cascade re-stales simulation-plan + rtl-design.
    _start_pass_complete("M1", "specification")
    # simulation-plan re-runs and passes — its prereq specification is back to pass/clean.
    # This pass does NOT touch the rework_decision targeting specification, so the only
    # rework_decision in the event log targets specification, not rtl-design.
    _start_pass_complete("M1", "simulation-plan")

    # cmd_dispatch(rtl-design) — rtl-design is pass/stale (cascade), and no rework_decision
    # targets rtl-design, so trigger is None. This is the cascade-rework path.
    r4 = cmd_dispatch("M1", "rtl-design")
    assert r4["ok"]
    assert r4["mode"] == "rework", (
        f"cascade rework should set mode=rework, got {r4['mode']}"
    )
    assert r4.get("rework_trigger") is None, (
        f"cascade rework should have no trigger, got {r4.get('rework_trigger')!r}"
    )

    # Invariant: prev artifacts (canonical result.json from prior rtl-design run)
    # remain on disk because cascade only touches task.json freshness, never
    # the canonical workdir (promote happens only on the next rtl-design pass).
    assert canonical_rtl_design_rj.exists(), (
        "cascade rework requires prev artifacts on disk (rework-trigger invariant)"
    )
