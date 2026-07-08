import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))

import orchestrate  # noqa: E402

STAGES = [
    "specification",
    "simulation-plan",
    "rtl-design",
    "lint-cdc",
    "synthesis",
    "timing-analysis",
    "simulation",
    "power-analysis",
    "frontend-signoff",
]


def _blank():
    return {
        "module": "m",
        "stages": {
            s: {
                "status": "not_started",
                "freshness": "clean",
                "current_run": None,
                "in_flight": [],
            }
            for s in STAGES
        },
    }


def _set(task, stage, status, fresh="clean", run=None, in_flight=None):
    task["stages"][stage] = {
        "status": status,
        "freshness": fresh,
        "current_run": run,
        "in_flight": in_flight or [],
    }


def _write(tmp, task, events=None):
    d = tmp / "asic" / "m"
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(json.dumps(task))
    (d / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in (events or []))
    )


def _next(tmp, monkeypatch, **kw):
    monkeypatch.chdir(tmp)
    return orchestrate.decide("m", **kw)


def test_done(tmp_path, monkeypatch):
    t = _blank()
    for s in STAGES:
        _set(t, s, "pass", run=1)
    _write(tmp_path, t)
    assert _next(tmp_path, monkeypatch)["action"] == "DONE"


def test_dispatch_first_eligible_main_thread(tmp_path, monkeypatch):
    _write(tmp_path, _blank())
    a = _next(tmp_path, monkeypatch)
    assert a == {
        "action": "DISPATCH",
        "stage": "specification",
        "kind": "main-thread",
        "ppa_targets": [],
    }


def test_phase1_sync_chain_advances_not_escalates(tmp_path, monkeypatch):
    # H1(c): after specification passes (sync, nothing in_flight), advance to
    # simulation-plan — NOT escalate.
    t = _blank()
    _set(t, "specification", "pass", run=1)
    _write(tmp_path, t)
    a = _next(tmp_path, monkeypatch)
    assert a["action"] == "DISPATCH" and a["stage"] == "simulation-plan"


def test_reap_then_dispatch_successor_one_turn(tmp_path, monkeypatch):
    # H1(b): power-analysis just completed; wake reaps it, then (next call)
    # frontend-signoff dispatches — no stall.
    t = _blank()
    for s in [
        "specification",
        "simulation-plan",
        "rtl-design",
        "lint-cdc",
        "synthesis",
        "timing-analysis",
        "simulation",
    ]:
        _set(t, s, "pass", run=1)
    _set(t, "power-analysis", "in_progress", run=1, in_flight=[{"run": 1}])
    _write(tmp_path, t)
    # wake reaps:
    assert _next(tmp_path, monkeypatch, wake="power-analysis:1") == {
        "action": "REAP",
        "stage": "power-analysis",
        "run": 1,
    }
    # after the LLM completes it (simulate pass), the loop re-queries:
    _set(t, "power-analysis", "pass", run=1)
    _write(tmp_path, t)
    a = _next(tmp_path, monkeypatch)
    assert a["action"] == "DISPATCH" and a["stage"] == "frontend-signoff"


def test_stale_wake_is_noop(tmp_path, monkeypatch):
    # L1: a --wake naming a run no longer in in_flight (already reaped) must NOT
    # produce a spurious REAP — it falls through to the normal decision.
    t = _blank()
    _set(t, "specification", "pass", run=1)  # specification done, not in_flight
    _write(tmp_path, t)
    a = _next(tmp_path, monkeypatch, wake="specification:1")
    assert a["action"] == "DISPATCH" and a["stage"] == "simulation-plan"  # not REAP


def test_malformed_wake_no_colon_is_noop(tmp_path, monkeypatch):
    # A malformed --wake (no colon / non-numeric run) must not crash — fall through.
    t = _blank()
    _write(tmp_path, t)
    a = _next(tmp_path, monkeypatch, wake="specification")
    assert (
        a["action"] == "DISPATCH" and a["stage"] == "specification"
    )  # normal decision, no crash
    a = _next(tmp_path, monkeypatch, wake="specification:abc")
    assert a["action"] == "DISPATCH" and a["stage"] == "specification"


def test_unknown_stage_wake_is_noop(tmp_path, monkeypatch):
    # An out-of-enum stage in --wake must not KeyError — fall through.
    t = _blank()
    _write(tmp_path, t)
    a = _next(tmp_path, monkeypatch, wake="bogus-stage:1")
    assert a["action"] == "DISPATCH" and a["stage"] == "specification"


def test_yield_when_inflight_no_eligible(tmp_path, monkeypatch):
    t = _blank()
    _set(t, "specification", "pass", run=1)
    _set(t, "simulation-plan", "pass", run=1)
    _set(t, "rtl-design", "pass", run=1)
    _set(t, "lint-cdc", "in_progress", run=1, in_flight=[{"run": 1}])
    _set(t, "simulation", "in_progress", run=1, in_flight=[{"run": 1}])
    _write(tmp_path, t)
    a = _next(tmp_path, monkeypatch)
    assert a["action"] == "YIELD"
    assert ["lint-cdc", 1] in a["in_flight"] and ["simulation", 1] in a["in_flight"]


def test_dispatch_task_with_ppa_targets(tmp_path, monkeypatch):
    t = _blank()
    for s in ["specification", "simulation-plan", "rtl-design", "lint-cdc"]:
        _set(t, s, "pass", run=1)
    _write(tmp_path, t)
    # write specification result.json with ppa_targets
    spec = tmp_path / "asic" / "m" / "Design" / "specification"
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "result.json").write_text(
        json.dumps(
            {
                "stage_specific": {
                    "ppa_targets": [
                        {"dim": "area_um2", "value": 1000},
                        {"dim": "power_mw", "value": 5},
                    ]
                }
            }
        )
    )
    a = _next(tmp_path, monkeypatch)
    assert a["stage"] == "synthesis" and a["kind"] == "task"
    assert a["ppa_targets"] == [
        {"dim": "area_um2", "value": 1000}
    ]  # power_mw filtered out


def test_failure_fixed_target_rework(tmp_path, monkeypatch):
    t = _blank()
    for s in ["specification", "simulation-plan", "rtl-design"]:
        _set(t, s, "pass", run=1)
    _set(t, "lint-cdc", "fail", run=1)
    _write(
        tmp_path,
        t,
        events=[
            {"type": "outcome", "stage": "lint-cdc", "run": 1, "result_status": "fail"}
        ],
    )
    a = _next(tmp_path, monkeypatch)
    assert (
        a["action"] == "REWORK"
        and a["failed_stage"] == "lint-cdc"
        and a["target_stage"] == "rtl-design"
    )


def test_simulation_fail_dispatches_triage_once(tmp_path, monkeypatch):
    t = _blank()
    for s in ["specification", "simulation-plan", "rtl-design"]:
        _set(t, s, "pass", run=1)
    _set(t, "simulation", "fail", run=1)
    _write(
        tmp_path,
        t,
        events=[
            {
                "type": "outcome",
                "stage": "simulation",
                "run": 1,
                "result_status": "fail",
            }
        ],
    )
    a = _next(tmp_path, monkeypatch)
    assert a["action"] == "DISPATCH_TRIAGE"
    assert a["sim_run"] == 1
    # L4: once a debug_dispatch is logged, re-query does NOT re-dispatch triage.
    ev = [
        {"type": "outcome", "stage": "simulation", "run": 1, "result_status": "fail"},
        {"type": "debug_dispatch", "module": "m"},
    ]
    _write(tmp_path, t, events=ev)
    assert _next(tmp_path, monkeypatch)["action"] == "YIELD"


def test_simulation_triage_analysis_routes(tmp_path, monkeypatch):
    t = _blank()
    for s in ["specification", "simulation-plan", "rtl-design"]:
        _set(t, s, "pass", run=1)
    _set(t, "simulation", "fail", run=1)
    _write(
        tmp_path,
        t,
        events=[
            {
                "type": "outcome",
                "stage": "simulation",
                "run": 1,
                "result_status": "fail",
            },
            {"type": "debug_dispatch", "module": "m"},
        ],
    )
    a = _next(
        tmp_path,
        monkeypatch,
        analysis={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
        },
    )
    assert a["action"] == "REWORK" and a["target_stage"] == "rtl-design"


def test_triage_high_confidence_routes(tmp_path, monkeypatch):
    t = _blank()
    for s in ["specification", "simulation-plan", "rtl-design"]:
        _set(t, s, "pass", run=1)
    _set(t, "simulation", "fail", run=1)
    _write(
        tmp_path,
        t,
        events=[
            {
                "type": "outcome",
                "stage": "simulation",
                "run": 1,
                "result_status": "fail",
            },
            {"type": "debug_dispatch", "module": "m"},
        ],
    )
    a = _next(
        tmp_path,
        monkeypatch,
        analysis={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "high",
        },
    )
    assert a["action"] == "REWORK" and a["target_stage"] == "rtl-design"


def test_triage_low_confidence_escalates(tmp_path, monkeypatch):
    t = _blank()
    for s in ["specification", "simulation-plan", "rtl-design"]:
        _set(t, s, "pass", run=1)
    _set(t, "simulation", "fail", run=1)
    _write(
        tmp_path,
        t,
        events=[
            {
                "type": "outcome",
                "stage": "simulation",
                "run": 1,
                "result_status": "fail",
            },
            {"type": "debug_dispatch", "module": "m"},
        ],
    )
    a = _next(
        tmp_path,
        monkeypatch,
        analysis={
            "analysis_state": "complete",
            "root_cause": "rtl-design",
            "confidence": "low",
        },
    )
    assert a["action"] == "ESCALATE"


def test_promote_failed_single_retry_then_escalate(tmp_path, monkeypatch):
    t = _blank()
    _set(t, "specification", "in_progress", run=1, in_flight=[{"run": 1}])
    base = [
        {
            "type": "outcome",
            "stage": "specification",
            "run": 1,
            "result_status": "promote_failed",
        }
    ]
    _write(tmp_path, t, events=base)
    assert _next(tmp_path, monkeypatch) == {
        "action": "REAP",
        "stage": "specification",
        "run": 1,
    }
    _write(tmp_path, t, events=base * 2)
    assert _next(tmp_path, monkeypatch)["action"] == "ESCALATE"


def test_escalate_when_stuck(tmp_path, monkeypatch):
    # Degenerate stuck state: nothing done, no fail/clean, no eligible, nothing
    # in-flight. simulation-plan is in_progress/clean (so NOT eligible) yet has an
    # empty in_flight[] (so nothing to wait on); rtl-design's prereq is therefore
    # not pass, so it is not eligible either. -> ESCALATE.
    t = _blank()
    _set(t, "specification", "pass", run=1)
    _set(t, "simulation-plan", "in_progress", fresh="clean", run=1, in_flight=[])
    _write(tmp_path, t)
    assert _next(tmp_path, monkeypatch)["action"] == "ESCALATE"
