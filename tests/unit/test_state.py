"""Tests for state.py — VeriPower orchestration state tool."""

import json
import sys
from pathlib import Path

import pytest
from _skills_sot import STAGE_SPECIFIC_MINIMAL
from conftest import bootstrap_prereqs_pass_clean, write_run_result

from framework.scripts import state, topology

# ── DAG constants ──


class TestDAGConstants:
    def test_prereq_keys_match_forward_priority(self):
        assert set(state.PREREQ_OF.keys()) == set(state.FORWARD_PRIORITY)

    def test_skill_keys_match_forward_priority(self):
        assert set(state.SKILL_OF.keys()) == set(state.FORWARD_PRIORITY)

    def test_result_dir_keys_match_forward_priority(self):
        assert set(topology._RESULT_DIR.keys()) == set(state.FORWARD_PRIORITY)

    def test_specification_has_no_prereqs(self):
        assert state.PREREQ_OF["specification"] == []

    def test_simulation_plan_depends_only_on_specification(self):
        """simulation-plan is driven by specification; RTL changes must NOT trigger a re-plan."""
        assert state.PREREQ_OF["simulation-plan"] == ["specification"]

    def test_simulation_depends_on_rtl_design(self):
        """simulation depends directly on rtl-design (single predecessor); lint-cdc is an independent synthesis-side chain."""
        assert state.PREREQ_OF["simulation"] == ["rtl-design"]

    def test_frontend_signoff_requires_only_power_analysis(self):
        """frontend-signoff's direct prerequisite is power-analysis; timing-analysis reaches it transitively through power-analysis."""
        assert state.PREREQ_OF["frontend-signoff"] == ["power-analysis"]

    def test_synthesis_requires_lint_cdc_not_rtl_design(self):
        assert state.PREREQ_OF["synthesis"] == ["lint-cdc"]

    def test_forward_priority_order(self):
        assert state.FORWARD_PRIORITY == [
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

    def test_simulation_plan_result_dir(self):
        assert topology._RESULT_DIR["simulation-plan"] == (
            "Verification",
            "simulation-plan",
        )

    def test_simulation_result_dir(self):
        assert topology._RESULT_DIR["simulation"] == ("Verification", "simulation")

    def test_log_allowed_types_is_2_orchestrator_types(self):
        """Only 2 orchestrator-writable log types remain: debug_dispatch / escalation."""
        assert state._LOG_ALLOWED_TYPES == {
            "debug_dispatch",
            "escalation",
        }

    def test_power_analysis_prereqs_post_merge(self):
        """After the merge, power-analysis's prereqs = simulation (data dependency) + timing-analysis (sequential gate).
        synthesis reaches power-analysis transitively through timing-analysis; no need to list it again."""
        assert state.PREREQ_OF["power-analysis"] == ["simulation", "timing-analysis"]

    def test_timing_analysis_requires_synthesis(self):
        """timing-analysis depends on synthesis (not power-analysis)."""
        assert state.PREREQ_OF["timing-analysis"] == ["synthesis"]

    def test_power_analysis_skill_registered(self):
        assert state.SKILL_OF["power-analysis"] == "veripower:power-analysis"

    def test_result_path_power_analysis(self):
        from pathlib import Path

        p = state._result_path("counter_4bit", "power-analysis")
        assert p == Path("asic/counter_4bit/Verification/power-analysis/result.json")


# ── DAG ancestor check ──


class TestIsAncestor:
    def test_specification_is_ancestor_of_frontend_signoff(self):
        assert state.is_dag_ancestor("specification", "frontend-signoff") is True

    def test_rtl_design_is_ancestor_of_lint_cdc(self):
        assert state.is_dag_ancestor("rtl-design", "lint-cdc") is True

    def test_simulation_plan_is_ancestor_of_simulation(self):
        assert state.is_dag_ancestor("simulation-plan", "simulation") is True

    def test_simulation_plan_is_ancestor_of_frontend_signoff(self):
        assert state.is_dag_ancestor("simulation-plan", "frontend-signoff") is True

    def test_rtl_design_is_ancestor_of_simulation(self):
        assert state.is_dag_ancestor("rtl-design", "simulation") is True

    def test_rtl_design_is_not_ancestor_of_simulation_plan(self):
        """Key DAG payoff: the plan is driven by specification, not by RTL."""
        assert state.is_dag_ancestor("rtl-design", "simulation-plan") is False

    def test_simulation_is_not_ancestor_of_anything_in_simulation_branch(self):
        assert state.is_dag_ancestor("simulation", "simulation-plan") is False
        assert state.is_dag_ancestor("simulation", "rtl-design") is False

    def test_stage_is_not_ancestor_of_itself(self):
        assert state.is_dag_ancestor("simulation-plan", "simulation-plan") is False
        assert state.is_dag_ancestor("simulation", "simulation") is False

    def test_synthesis_is_not_ancestor_of_simulation(self):
        """synthesis and simulation are parallel branches."""
        assert state.is_dag_ancestor("synthesis", "simulation") is False

    def test_simulation_is_power_analysis_ancestor(self):
        """After the merge: simulation has a direct edge → power-analysis (data dependency)."""
        assert state.is_dag_ancestor("simulation", "power-analysis") is True

    def test_timing_analysis_gates_power_analysis(self):
        """timing-analysis sequential-gate edge → power-analysis (unchanged)."""
        assert state.is_dag_ancestor("timing-analysis", "power-analysis") is True

    def test_synthesis_reaches_power_analysis_via_timing(self):
        """synthesis reaches power-analysis indirectly through timing-analysis (transitive)."""
        assert state.is_dag_ancestor("synthesis", "power-analysis") is True

    def test_timing_analysis_is_ancestor_of_frontend_signoff(self):
        """After narrowing frontend-signoff's direct prereqs, timing-analysis is still guaranteed by transitive dependency."""
        assert state.is_dag_ancestor("timing-analysis", "frontend-signoff") is True

    def test_synthesis_is_ancestor_of_frontend_signoff(self):
        """synthesis reaches frontend-signoff via transitive dependency (multiple paths)."""
        assert state.is_dag_ancestor("synthesis", "frontend-signoff") is True


# ── I/O helpers ──


class TestIO:
    def test_task_path(self):
        p = state._task_path("counter_4bit")
        assert p == Path("asic/counter_4bit/task.json")

    def test_events_path(self):
        p = state._events_path("counter_4bit")
        assert p == Path("asic/counter_4bit/events.jsonl")

    def test_result_path(self):
        p = state._result_path("counter_4bit", "lint-cdc")
        assert p == Path("asic/counter_4bit/Design/lint-cdc/result.json")

    def test_read_task_missing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            state.read_task("nonexistent")

    def test_read_write_task_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task = state._blank_task("mymod")
        p = state._task_path("mymod")
        p.parent.mkdir(parents=True)
        state.write_task("mymod", task)
        assert state.read_task("mymod") == task

    def test_write_task_atomic(self, tmp_path, monkeypatch):
        """write_task uses tmp+rename — no .json.tmp residue."""
        monkeypatch.chdir(tmp_path)
        task = state._blank_task("mymod")
        p = state._task_path("mymod")
        p.parent.mkdir(parents=True)
        state.write_task("mymod", task)
        assert not p.with_suffix(".json.tmp").exists()

    def test_append_and_read_events(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ep = state._events_path("m")
        ep.parent.mkdir(parents=True)
        state.append_event(
            "m",
            {
                "type": "dispatch",
                "stage": "rtl-design",
                "mode": "forward",
                "run": 1,
                "workdir": "asic/m/Design/rtl-design/runs/1/",
            },
        )
        state.append_event(
            "m",
            {
                "type": "outcome",
                "stage": "rtl-design",
                "run": 1,
                "result_status": "pass",
            },
        )
        events = state.read_events("m")
        assert len(events) == 2
        assert events[0]["type"] == "dispatch"
        assert events[1]["type"] == "outcome"
        assert "ts" in events[0]  # timestamp auto-injected

    def test_read_events_tolerates_truncated_last_line(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ep = state._events_path("m")
        ep.parent.mkdir(parents=True)
        ep.write_text('{"type":"dispatch","stage":"rtl-design"}\n{"trunca')
        events = state.read_events("m")
        assert len(events) == 1

    def test_read_events_empty_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ep = state._events_path("m")
        ep.parent.mkdir(parents=True)
        ep.write_text("")
        assert state.read_events("m") == []

    def test_read_events_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert state.read_events("m") == []

    def test_now_iso_has_microsecond_precision(self):
        ts = state._now_iso()
        # Format: 2026-04-22T14:30:45.123456Z
        import re

        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$", ts), (
            f"unexpected ts format: {ts!r}"
        )

    def test_append_event_accepts_explicit_ts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ep = state._events_path("m")
        ep.parent.mkdir(parents=True)
        fixed_ts = "2026-04-22T14:30:45.123456Z"
        state.append_event(
            "m",
            {
                "type": "dispatch",
                "stage": "rtl-design",
                "mode": "forward",
                "run": 1,
                "workdir": "asic/m/Design/rtl-design/runs/1/",
            },
            ts=fixed_ts,
        )
        events = state.read_events("m")
        assert events[0]["ts"] == fixed_ts

    def test_append_event_generates_ts_when_omitted(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ep = state._events_path("m")
        ep.parent.mkdir(parents=True)
        state.append_event(
            "m",
            {
                "type": "dispatch",
                "stage": "rtl-design",
                "mode": "forward",
                "run": 1,
                "workdir": "asic/m/Design/rtl-design/runs/1/",
            },
        )
        events = state.read_events("m")
        assert "ts" in events[0] and events[0]["ts"].endswith("Z")


# ── reason validation ──


class TestValidateReason:
    def test_none_rejected(self):
        assert state._validate_reason(None) is not None

    def test_empty_rejected(self):
        assert state._validate_reason("") is not None

    def test_whitespace_only_rejected(self):
        assert state._validate_reason("   \t\n  ") is not None

    def test_non_empty_accepted(self):
        assert state._validate_reason("W415a: signal q multi-driven") is None

    def test_short_still_accepted(self):
        """Length threshold is intentionally absent — only whitespace is rejected."""
        assert state._validate_reason("a") is None

    def test_error_message_is_string(self):
        err = state._validate_reason("")
        assert isinstance(err, str) and err


# ── cascade-stale ──


class TestCascadeStale:
    """cascade_stale wrapper deleted; these tests use _compute_cascade (pure BFS)."""

    def _make_task(self, tmp_path, monkeypatch, overrides=None):
        monkeypatch.chdir(tmp_path)
        task = state._blank_task("m")
        if overrides:
            for stage, vals in overrides.items():
                task["stages"][stage].update(vals)
        p = state._task_path("m")
        p.parent.mkdir(parents=True)
        state.write_task("m", task)
        return task

    def test_cascade_returns_dict_list(self, tmp_path, monkeypatch):
        """_compute_cascade BFS from rtl-design stales all downstream pass stages."""
        task = self._make_task(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "rtl-design": {"status": "pass"},
                "lint-cdc": {"status": "pass"},
                "simulation": {"status": "pass"},
                "synthesis": {"status": "pass"},
                "timing-analysis": {"status": "pass"},
                "frontend-signoff": {"status": "pass"},
            },
        )
        staled = state._compute_cascade(task, "rtl-design")
        stages = {item["stage"] for item in staled}
        assert stages == {
            "lint-cdc",
            "simulation",
            "synthesis",
            "timing-analysis",
            "frontend-signoff",
        }
        # staled entries are {stage: ...} only (no archive field)
        for item in staled:
            assert set(item.keys()) == {"stage"}

    def test_cascade_skips_not_started(self, tmp_path, monkeypatch):
        task = self._make_task(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "rtl-design": {"status": "pass"},
            },
        )
        staled = state._compute_cascade(task, "rtl-design")
        assert staled == []

    def test_cascade_skips_already_stale(self, tmp_path, monkeypatch):
        task = self._make_task(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "rtl-design": {"status": "pass"},
                "lint-cdc": {"status": "pass", "freshness": "stale"},
            },
        )
        staled = state._compute_cascade(task, "rtl-design")
        assert staled == []

    def test_cascade_includes_in_progress(self, tmp_path, monkeypatch):
        """in_progress stages are now staled."""
        task = self._make_task(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "rtl-design": {"status": "pass"},
                "lint-cdc": {"status": "in_progress"},
            },
        )
        staled = state._compute_cascade(task, "rtl-design")
        assert len(staled) == 1
        assert staled[0]["stage"] == "lint-cdc"

    def test_cascade_marks_fail_as_stale(self, tmp_path, monkeypatch):
        task = self._make_task(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "rtl-design": {"status": "pass"},
                "lint-cdc": {"status": "fail"},
            },
        )
        staled = state._compute_cascade(task, "rtl-design")
        assert len(staled) == 1
        assert staled[0]["stage"] == "lint-cdc"
        # in-memory mutation — freshness flipped in task dict
        assert task["stages"]["lint-cdc"]["freshness"] == "stale"


# ── init command ──


class TestCmdInit:
    def test_init_creates_task_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = state.cmd_init("mymod")
        assert result == {"ok": True, "created": True}
        t = state.read_task("mymod")
        assert t["module"] == "mymod"
        assert all(
            t["stages"][s]["status"] == "not_started" for s in state.FORWARD_PRIORITY
        )

    def test_init_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("mymod")
        result = state.cmd_init("mymod")
        assert result == {"ok": True, "created": False}

    def test_init_does_not_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("mymod")
        t = state.read_task("mymod")
        t["stages"]["specification"]["status"] = "pass"
        state.write_task("mymod", t)
        state.cmd_init("mymod")
        t2 = state.read_task("mymod")
        assert t2["stages"]["specification"]["status"] == "pass"


# ── status command ──


class TestCmdStatus:
    def test_status_fresh_module(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_status("m")
        assert result["module"] == "m"
        assert set(result["stages"]) == set(state.FORWARD_PRIORITY)
        for s in state.FORWARD_PRIORITY:
            assert result["stages"][s]["status"] == "not_started"
            assert result["stages"][s]["freshness"] == "clean"

    def test_status_with_mixed_states(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        t = state.read_task("m")
        t["stages"]["specification"]["status"] = "pass"
        t["stages"]["rtl-design"]["status"] = "fail"
        t["stages"]["lint-cdc"]["status"] = "pass"
        t["stages"]["lint-cdc"]["freshness"] = "stale"
        t["stages"]["simulation"]["status"] = "in_progress"
        state.write_task("m", t)
        result = state.cmd_status("m")
        assert result["stages"]["specification"]["status"] == "pass"
        assert result["stages"]["rtl-design"]["status"] == "fail"
        assert result["stages"]["lint-cdc"]["status"] == "pass"
        assert result["stages"]["lint-cdc"]["freshness"] == "stale"
        assert result["stages"]["simulation"]["status"] == "in_progress"


# ── dispatch command ──


class TestCmdStart:
    def _setup_module(self, tmp_path, monkeypatch, overrides=None):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        if overrides:
            t = state.read_task("m")
            for stage, vals in overrides.items():
                t["stages"][stage].update(vals)
            state.write_task("m", t)

    def test_dispatch_forward_specification(self, tmp_path, monkeypatch):
        self._setup_module(tmp_path, monkeypatch)
        result = state.cmd_dispatch("m", "specification")
        assert result["ok"] is True
        assert result["mode"] == "forward"
        assert result["skill"] == "veripower:specification"
        assert result["upstream_results"] == []
        assert "rework_trigger" not in result
        t = state.read_task("m")
        assert t["stages"]["specification"]["status"] == "in_progress"
        events = state.read_events("m")
        assert len(events) == 1
        assert events[0]["type"] == "dispatch"
        assert events[0]["mode"] == "forward"

    def test_dispatch_forward_rtl_design_after_simulation_plan_pass(
        self, tmp_path, monkeypatch
    ):
        """rtl-design prereq is simulation-plan (not specification)."""
        self._setup_module(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "simulation-plan": {"status": "pass"},
            },
        )
        result = state.cmd_dispatch("m", "rtl-design")
        assert result["ok"] is True
        assert result["mode"] == "forward"
        assert result["upstream_results"] == [
            "Verification/simulation-plan/result.json"
        ]

    def test_dispatch_rejects_unmet_prereqs(self, tmp_path, monkeypatch):
        self._setup_module(tmp_path, monkeypatch)  # specification is not_started
        result = state.cmd_dispatch("m", "rtl-design")
        assert result["ok"] is False
        assert "prerequisite" in result["error"]

    def test_dispatch_rejects_already_in_progress(self, tmp_path, monkeypatch):
        self._setup_module(
            tmp_path, monkeypatch, {"specification": {"status": "in_progress"}}
        )
        result = state.cmd_dispatch("m", "specification")
        assert result["ok"] is False
        assert "in_progress" in result["error"]

    def test_dispatch_rework_mode_for_stale(self, tmp_path, monkeypatch):
        """rtl-design prereq is simulation-plan; must have simulation-plan pass/clean for rtl-design rework.
        rework_trigger points at the failed stage's canonical result.json
        (canonical = latest run regardless of pass/fail)."""
        self._setup_module(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "simulation-plan": {"status": "pass"},
                "rtl-design": {"status": "pass", "freshness": "stale"},
            },
        )
        # Plant a rework_decision event so rework_trigger is resolved.
        # `run` field retained for audit; not used by trigger resolution.
        state.append_event(
            "m",
            {
                "type": "rework_decision",
                "failed_stage": "lint-cdc",
                "target_stage": "rtl-design",
                "reason": "W415a",
                "run": 3,
            },
        )
        result = state.cmd_dispatch("m", "rtl-design")
        assert result["ok"] is True
        assert result["mode"] == "rework"
        assert result["rework_trigger"] == "Design/lint-cdc/result.json"

    def test_dispatch_rework_no_trigger_for_cascade_stale(self, tmp_path, monkeypatch):
        """pass/stale from cascade — no rework_decision targeting this stage."""
        self._setup_module(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "rtl-design": {"status": "pass"},
                "lint-cdc": {"status": "pass", "freshness": "stale"},
            },
        )
        result = state.cmd_dispatch("m", "lint-cdc")
        assert result["ok"] is True
        assert result["mode"] == "rework"
        assert "rework_trigger" not in result

    def test_dispatch_dispatch_event_has_no_prompt_summary(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        r = state.cmd_dispatch("m", "specification")
        assert r["ok"] is True
        events = state.read_events("m")
        dispatch = [e for e in events if e["type"] == "dispatch"][0]
        assert "prompt_summary" not in dispatch

    def test_cmd_dispatch_with_orchestrator_context_writes_sibling(
        self, tmp_path, monkeypatch
    ):
        """cmd_dispatch orchestrator_context_source → writes a sibling file on disk + returns the path field."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        content = "# Triage hint\n- root_cause: rtl-design\n- location: mod_a.sv:42\n"
        r = state.cmd_dispatch(
            "m", "specification", orchestrator_context_source=content
        )
        assert r["ok"]
        assert "orchestrator_context_path" in r
        expected_path = "Design/specification/runs/1/orchestrator-context.md"
        assert r["orchestrator_context_path"] == expected_path
        abs_path = Path("asic/m") / expected_path
        assert abs_path.exists()
        assert abs_path.read_text() == content

    def test_cmd_dispatch_without_orchestrator_context(self, tmp_path, monkeypatch):
        """when orchestrator_context_source is not supplied, no sibling file is created and the return value has no path field."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        r = state.cmd_dispatch("m", "specification")
        assert r["ok"]
        assert "orchestrator_context_path" not in r
        abs_path = Path("asic/m/Design/specification/runs/1/orchestrator-context.md")
        assert not abs_path.exists()

    def test_dispatch_frontend_signoff_blocks_when_power_analysis_missing(
        self, tmp_path, monkeypatch
    ):
        """frontend-signoff direct prereq = power-analysis (T2 narrowing).
        timing-analysis directly gates power-analysis (sequential gate) and reaches signoff through power-analysis."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        task = state.read_task("foo")
        for s in [
            "specification",
            "simulation-plan",
            "rtl-design",
            "lint-cdc",
            "synthesis",
            "timing-analysis",
            "simulation",
        ]:
            task["stages"][s] = {
                "status": "pass",
                "freshness": "clean",
                "current_run": 1,
                "in_flight": [],
            }
        # power-analysis deliberately not_started
        state.write_task("foo", task)
        result = state.cmd_dispatch("foo", "frontend-signoff")
        assert result["ok"] is False
        assert "power-analysis" in result["error"]

    def test_dispatch_rejects_fail_clean(self, tmp_path, monkeypatch):
        """fail/clean must be routed to rework, not start. cmd_dispatch rejects it
        even when prereqs are pass/clean — this guards the rework branch order
        (Orchestrator must call cmd_rework, not cmd_dispatch, for failed stages)."""
        self._setup_module(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "simulation-plan": {"status": "fail"},  # prereqs ok, self failed
            },
        )
        result = state.cmd_dispatch("m", "simulation-plan")
        assert result["ok"] is False
        assert "fail" in result["error"]

    def test_dispatch_in_progress_stale_redispatchable(self, tmp_path, monkeypatch):
        """cascade can hit a running stage, marking it in_progress/stale.
        cmd_dispatch must accept this state for re-dispatch (multi-run coexistence)."""
        self._setup_module(
            tmp_path,
            monkeypatch,
            {
                "specification": {"status": "pass"},
                "simulation-plan": {"status": "pass"},
                "rtl-design": {"status": "pass"},
                "simulation": {
                    "status": "in_progress",
                    "freshness": "stale",
                    "current_run": 1,
                    "in_flight": [{"run": 1}],
                },
            },
        )
        result = state.cmd_dispatch("m", "simulation")
        assert result["ok"] is True
        assert result["mode"] == "rework"
        assert result["run"] == 2  # new run alongside the old in_flight one
        # both runs now in flight
        t = state.read_task("m")
        runs = {x["run"] for x in t["stages"]["simulation"]["in_flight"]}
        assert runs == {1, 2}


# ── reap command ──


class TestCmdComplete:
    _STAGE_SPECIFIC: dict = STAGE_SPECIFIC_MINIMAL

    def _setup_in_progress(
        self, tmp_path, monkeypatch, stage="rtl-design", extra_overrides=None
    ):
        """Set up a stage as in_progress/clean with run=1 via cmd_dispatch, plus
        a schema-valid runs/1/result.json (validate_result reads before promote).
        """
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        bootstrap_prereqs_pass_clean("m", stage)
        if extra_overrides:
            t = state.read_task("m")
            for s, vals in extra_overrides.items():
                t["stages"][s].update(vals)
            state.write_task("m", t)
        r = state.cmd_dispatch("m", stage)
        assert r["ok"], f"cmd_dispatch failed: {r}"
        write_run_result("m", stage, 1)

    def test_reap_pass(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "completed"
        assert result["result_status"] == "pass"
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["status"] == "pass"
        assert t["stages"]["rtl-design"]["freshness"] == "clean"

    def test_reap_fail_promotes_to_canonical(self, tmp_path, monkeypatch):
        """After a fail outcome, canonical exists and status=fail."""
        self._setup_in_progress(tmp_path, monkeypatch, "rtl-design")
        # Overwrite run-specific result.json with status=fail
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {"fail_reason": "test fail"},
                }
            )
        )
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="fail")
        assert result["action"] == "completed"
        assert result["result_status"] == "fail"
        # canonical exists post-promote
        canonical_rj = state._result_path("m", "rtl-design")
        assert canonical_rj.exists()
        assert json.loads(canonical_rj.read_text())["status"] == "fail"

    def test_reap_fail_canonical_holds_fail_status(self, tmp_path, monkeypatch):
        """canonical.status field = 'fail'; the return value does not carry result_path."""
        self._setup_in_progress(tmp_path, monkeypatch, "rtl-design")
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {"fail_reason": "test fail"},
                }
            )
        )
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="fail")
        # result_path field removed (canonical replaces it)
        assert "result_path" not in result
        canonical_rj = state._result_path("m", "rtl-design")
        canonical_data = json.loads(canonical_rj.read_text())
        assert canonical_data["status"] == "fail"

    def test_reap_fail_promote_failed_keeps_in_progress(self, tmp_path, monkeypatch):
        """On the fail path, a promote() exception → promote_failed; state remains in_progress."""
        self._setup_in_progress(tmp_path, monkeypatch, "rtl-design")
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "fail",
                    "artifacts": [
                        {"path": "nonexistent.v"}
                    ],  # promote will fail: artifact missing
                    "stage_specific": {"fail_reason": "test fail"},
                }
            )
        )
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="fail")
        assert result["action"] == "promote_failed"
        assert "FileNotFoundError" in result["reason"]
        # state stays in_progress; run remains in_flight for retry
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["status"] == "in_progress"
        assert {"run": 1} in t["stages"]["rtl-design"]["in_flight"]

    def test_reap_pass_cascades(self, tmp_path, monkeypatch):
        """rtl-design pass cascade-stales its pass/clean child lint-cdc."""
        self._setup_in_progress(
            tmp_path,
            monkeypatch,
            "rtl-design",
            {
                "lint-cdc": {
                    "status": "pass",
                    "freshness": "clean",
                    "current_run": 1,
                    "in_flight": [],
                },
            },
        )
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "completed"
        assert result["result_status"] == "pass"
        staled_stages = {x["stage"] for x in result["staled"]}
        assert "lint-cdc" in staled_stages
        t = state.read_task("m")
        assert t["stages"]["lint-cdc"]["freshness"] == "stale"

    def test_reap_pass_no_cascade_means_single_event(self, tmp_path, monkeypatch):
        """When rtl-design has no stale-able children, no cascade event is written."""
        self._setup_in_progress(tmp_path, monkeypatch)
        # rtl-design's children (lint-cdc, simulation) are not_started by default → nothing to stale
        state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        events = state.read_events("m")
        outcome_events = [e for e in events if e["type"] == "outcome"]
        assert len(outcome_events) == 1
        assert outcome_events[0]["result_status"] == "pass"
        # No pass/fail/in_progress children → no cascade event
        assert not any(e["type"] == "cascade" for e in events)

    def test_reap_pass_outcome_ts_matches_cascade_ts(self, tmp_path, monkeypatch):
        """outcome + cascade events share ts (single transaction)."""
        self._setup_in_progress(
            tmp_path,
            monkeypatch,
            "rtl-design",
            {
                "lint-cdc": {
                    "status": "pass",
                    "freshness": "clean",
                    "current_run": 1,
                    "in_flight": [],
                },
            },
        )
        state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        events = state.read_events("m")
        outcome_events = [e for e in events if e["type"] == "outcome"]
        assert len(outcome_events) == 1
        assert outcome_events[0]["ts"]
        cascade_events = [e for e in events if e["type"] == "cascade"]
        assert len(cascade_events) == 1
        assert outcome_events[0]["ts"] == cascade_events[0]["ts"]

    def test_reap_pass_outcome_event_flat_shape(self, tmp_path, monkeypatch):
        """outcome uses a single result_status — no separate status/discarded fields."""
        self._setup_in_progress(tmp_path, monkeypatch)
        state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        events = state.read_events("m")
        outcome = [e for e in events if e["type"] == "outcome"][0]
        assert outcome["result_status"] == "pass"
        assert "status" not in outcome
        assert "discarded" not in outcome
        assert "reason" not in outcome
        assert "archive" not in outcome

    def test_reap_fail(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        # write fail result to run-specific path (validate_result reads runs/<N>/result.json)
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {"fail_reason": "test fail"},
                }
            )
        )
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="fail")
        assert result["action"] == "completed"
        assert result["result_status"] == "fail"
        # fail branch returns staled=[] for symmetry with pass — callers can always
        # do result["staled"] without special-casing the outcome.
        assert result["staled"] == []
        # result_path field removed: canonical is now the latest run
        # (pass or fail), so Orchestrator reads canonical directly — no need for a
        # separate run-specific path in the return.
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["status"] == "fail"

    def test_rework_trigger_resolves_to_canonical_first_time(
        self, tmp_path, monkeypatch
    ):
        """after a first-time fail, trigger = canonical path; the file exists."""
        # 1. Setup rtl-design eligible (prereqs pass/clean) and in_progress, run=1
        self._setup_in_progress(tmp_path, monkeypatch, "rtl-design")
        # 2. Write fail result.json at run-specific path
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {"fail_reason": "test fail"},
                }
            )
        )
        # 3. cmd_reap fail → canonical now has fail data (promote on fail)
        state.cmd_reap("m", "rtl-design", run=1, outcome="fail")
        # 4. Orchestrator decides rework: failed=rtl-design → target=specification
        state.cmd_rework(
            "m",
            failed_stage="rtl-design",
            target_stage="specification",
            reason="cascade",
        )
        # 5. Dispatch specification → trigger should resolve to rtl-design canonical
        r = state.cmd_dispatch("m", "specification")
        assert r["ok"]
        assert r["mode"] == "rework"
        trigger = r["rework_trigger"]
        # Should be canonical path (no /runs/N/ segment)
        assert "/runs/" not in trigger
        assert trigger == "Design/rtl-design/result.json"
        # File actually exists at the trigger path
        abs_trigger = Path("asic/m") / trigger
        assert abs_trigger.exists()

    def test_reap_fail_schema_bad_goes_to_invalid(self, tmp_path, monkeypatch):
        """fail outcome with broken result.json → invalid (symmetric with pass)."""
        self._setup_in_progress(tmp_path, monkeypatch)
        # overwritethe run-specific result.json with bad schema
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text('{"bad": "schema"}')
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="fail")
        assert result["action"] == "invalid"

    def test_reap_blocked(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        result = state.cmd_reap(
            "m", "rtl-design", run=1, outcome="blocked", reason="no license"
        )
        assert result["action"] == "blocked"
        assert result["reason"] == "no license"
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["status"] == "not_started"

    def test_reap_blocked_rejects_empty_reason(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="blocked", reason="")
        assert result["ok"] is False
        assert "reason" in result["error"]

    def test_reap_blocked_rejects_missing_reason(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="blocked")
        assert result["ok"] is False

    def test_reap_pass_rejects_reason(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        result = state.cmd_reap(
            "m", "rtl-design", run=1, outcome="pass", reason="explaining myself"
        )
        assert result["ok"] is False
        assert "not accepted" in result["error"]

    def test_reap_fail_rejects_reason(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        # write fail result to run-specific path
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {"fail_reason": "test fail"},
                }
            )
        )
        result = state.cmd_reap(
            "m", "rtl-design", run=1, outcome="fail", reason="also fail detail"
        )
        assert result["ok"] is False

    def test_reap_rejects_not_in_progress(self, tmp_path, monkeypatch):
        """calling complete on a stage with no in_flight run → stale_dispatch discard.

        cmd_reap uses an in_flight membership check rather than an
        in_progress guard; the result is no state mutation, expressed as a
        discarded outcome rather than a hard error.
        """
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "discarded"
        assert result["reason_code"] == "stale_dispatch"

    def test_reap_invalid_result_schema(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        # overwriterun-specific result.json with bad schema
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text('{"bad": "schema"}')
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "invalid"
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["status"] == "not_started"

    def test_reap_invalid_event_carries_reason(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        # overwriterun-specific result.json with bad schema
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text('{"bad": "schema"}')
        state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        events = state.read_events("m")
        outcome = [e for e in events if e["type"] == "outcome"][0]
        assert outcome["result_status"] == "invalid"
        assert outcome["reason"]  # validator error message captured

    def test_reap_pass_discards_if_prereqs_changed(self, tmp_path, monkeypatch):
        """prereq stale during exec → discarded (prereq_changed).
        Non-success finalize: canonical absent → not_started/clean."""
        self._setup_in_progress(tmp_path, monkeypatch)
        t = state.read_task("m")
        t["stages"]["simulation-plan"]["freshness"] = "stale"
        state.write_task("m", t)
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "discarded"
        assert result["reason_code"] == "prereq_changed"
        t = state.read_task("m")
        # canonical absent → not_started/clean
        assert t["stages"]["rtl-design"]["status"] == "not_started"
        assert t["stages"]["rtl-design"]["freshness"] == "clean"

    def test_reap_discarded_archives_result(self, tmp_path, monkeypatch):
        """prereq_changed discard → no archive (canonical absent → not_started/clean).
        The run result.json stays in runs/<N>/ (not promoted to canonical).
        No archive key in return dict."""
        self._setup_in_progress(tmp_path, monkeypatch)
        t = state.read_task("m")
        t["stages"]["simulation-plan"]["freshness"] = "stale"
        state.write_task("m", t)
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "discarded"
        # no archive in discarded — run result stays in runs/1/result.json, not promoted
        assert "archive" not in result
        # canonical result.json absent (not promoted)
        assert not state._result_path("m", "rtl-design").exists()

    def test_reap_discarded_event_shape(self, tmp_path, monkeypatch):
        """prereq_changed discard event has reason but no archive field."""
        self._setup_in_progress(tmp_path, monkeypatch)
        t = state.read_task("m")
        t["stages"]["simulation-plan"]["freshness"] = "stale"
        state.write_task("m", t)
        state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        events = state.read_events("m")
        outcome = [e for e in events if e["type"] == "outcome"][0]
        assert outcome["result_status"] == "discarded"
        assert outcome["reason"]
        # no archive in discarded event (run stays in runs/<N>/)
        assert "archive" not in outcome
        # no cascade event for discarded
        assert not any(e["type"] == "cascade" for e in events)

    def test_reap_writes_outcome_event(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        events = state.read_events("m")
        outcome_events = [e for e in events if e["type"] == "outcome"]
        assert len(outcome_events) == 1
        assert outcome_events[0]["stage"] == "rtl-design"
        assert outcome_events[0]["result_status"] == "pass"

    def test_reap_self_listed_result_json_is_invalid_not_promote_failed(
        self, tmp_path, monkeypatch
    ):
        """End-to-end left-shift: a result.json that self-lists result.json is
        rejected at validation (action=invalid), NOT at promote (promote_failed).
        This turns the 11x promote_failed churn from sdc_controller-20260529 into a
        single clean validation failure."""
        self._setup_in_progress(tmp_path, monkeypatch, "lint-cdc")
        # Overwrite the run result.json: schema-valid except artifacts self-lists result.json.
        write_run_result("m", "lint-cdc", 1, artifacts=[{"path": "result.json"}])
        result = state.cmd_reap("m", "lint-cdc", run=1, outcome="pass")
        assert result["action"] == "invalid"
        # State untouched — validation rejected before any promote.
        t = state.read_task("m")
        assert t["stages"]["lint-cdc"]["status"] == "not_started"

    @pytest.mark.parametrize(
        "bad_path",
        ["../escape.txt", "/abs/escape.txt", "sub/../../escape.txt", ".."],
    )
    def test_reap_traversal_path_is_invalid_not_promote_failed(
        self, tmp_path, monkeypatch, bad_path
    ):
        """End-to-end left-shift: a result.json whose artifacts[] path escapes the
        run dir (`..` traversal or absolute) is rejected at validate_result
        (action=invalid), NOT at promote. Same shape as the self-listing guard."""
        self._setup_in_progress(tmp_path, monkeypatch, "lint-cdc")
        write_run_result("m", "lint-cdc", 1, artifacts=[{"path": bad_path}])
        result = state.cmd_reap("m", "lint-cdc", run=1, outcome="pass")
        assert result["action"] == "invalid"
        # State untouched — validation rejected before any promote.
        t = state.read_task("m")
        assert t["stages"]["lint-cdc"]["status"] == "not_started"

    def test_reap_stale_dispatch_return_has_result_status(self, tmp_path, monkeypatch):
        """Every cmd_reap return carries result_status mirroring the event log
        (an ancillary work item). stale_dispatch → result_status='discarded'."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "discarded"
        assert result["result_status"] == "discarded"

    def test_reap_blocked_return_has_result_status(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        result = state.cmd_reap(
            "m", "rtl-design", run=1, outcome="blocked", reason="no license"
        )
        assert result["action"] == "blocked"
        assert result["result_status"] == "blocked"

    def test_reap_invalid_return_has_result_status(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text('{"bad": "schema"}')
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "invalid"
        assert result["result_status"] == "invalid"

    def test_reap_promote_failed_return_has_result_status(self, tmp_path, monkeypatch):
        self._setup_in_progress(tmp_path, monkeypatch)
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "pass",
                    "artifacts": [
                        {"path": "nonexistent.v"}
                    ],  # promote fails: artifact missing
                    "stage_specific": {},
                }
            )
        )
        result = state.cmd_reap("m", "rtl-design", run=1, outcome="pass")
        assert result["action"] == "promote_failed"
        assert result["result_status"] == "promote_failed"

    def test_reap_derive_pass_no_outcome(self, tmp_path, monkeypatch):
        """Derive mode: omit --outcome → cmd_reap reads the run
        result.json itself and resolves pass. Orchestrator reads nothing."""
        self._setup_in_progress(
            tmp_path, monkeypatch
        )  # writes a valid pass result.json
        result = state.cmd_reap("m", "rtl-design", run=1)  # no outcome
        assert result["action"] == "completed"
        assert result["result_status"] == "pass"

    def test_reap_derive_fail_no_outcome(self, tmp_path, monkeypatch):
        """Derive mode: omit --outcome with a valid fail result.json → resolves fail."""
        self._setup_in_progress(tmp_path, monkeypatch)
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "rtl-design",
                    "module": "m",
                    "produced_at": "2026-04-22T00:00:00.000000Z",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {"fail_reason": "x"},
                }
            )
        )
        result = state.cmd_reap("m", "rtl-design", run=1)  # no outcome
        assert result["action"] == "completed"
        assert result["result_status"] == "fail"

    def test_reap_derive_blocked_when_result_json_missing(self, tmp_path, monkeypatch):
        """No result.json → blocked 'crash recovery' (NOT invalid)."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        bootstrap_prereqs_pass_clean("m", "rtl-design")
        r = state.cmd_dispatch("m", "rtl-design")
        assert r["ok"]
        # deliberately do NOT write runs/1/result.json
        result = state.cmd_reap("m", "rtl-design", run=1)  # no outcome
        assert result["result_status"] == "blocked"
        assert "missing" in result["reason"]

    def test_reap_derive_blocked_when_status_malformed(self, tmp_path, monkeypatch):
        """Valid JSON but status not in {pass,fail} → blocked 'malformed' (before validate)."""
        self._setup_in_progress(tmp_path, monkeypatch)
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(json.dumps({"status": "weird"}))
        result = state.cmd_reap("m", "rtl-design", run=1)  # no outcome
        assert result["result_status"] == "blocked"
        assert "malformed" in result["reason"]

    def test_reap_derive_schema_invalid_is_invalid_not_blocked(
        self, tmp_path, monkeypatch
    ):
        """status='pass' but schema-broken → invalid (NOT blocked) — the distinction
        derive mode must preserve (crash/missing=blocked vs schema-bad=invalid)."""
        self._setup_in_progress(tmp_path, monkeypatch)
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text(json.dumps({"status": "pass"}))  # status ok, rest missing
        result = state.cmd_reap("m", "rtl-design", run=1)  # no outcome
        assert result["result_status"] == "invalid"

    def test_reap_derive_rejects_reason(self, tmp_path, monkeypatch):
        """Omitting --outcome but passing --reason is a misuse: derive mode supplies
        its own blocked reason."""
        self._setup_in_progress(tmp_path, monkeypatch)
        result = state.cmd_reap("m", "rtl-design", run=1, reason="stray")  # no outcome
        assert result["ok"] is False
        assert "reason" in result["error"]

    def test_reap_derive_blocked_when_result_json_not_dict(self, tmp_path, monkeypatch):
        """Valid JSON but not an object (e.g. null / [] from a truncated write) →
        blocked, not an uncaught AttributeError (crash robustness)."""
        self._setup_in_progress(tmp_path, monkeypatch)
        run_rj = (
            state._result_path("m", "rtl-design").parent / "runs" / "1" / "result.json"
        )
        run_rj.write_text("null")
        result = state.cmd_reap("m", "rtl-design", run=1)  # no outcome
        assert result["result_status"] == "blocked"
        assert "object" in result["reason"]


# ── rework command ──


class TestCmdRework:
    def _setup(self, tmp_path, monkeypatch, overrides=None, write_results_for=None):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        t = state.read_task("m")
        defaults = {
            "specification": {"status": "pass"},
            "rtl-design": {"status": "pass"},
            "lint-cdc": {"status": "fail"},
        }
        defaults.update(overrides or {})
        for s, vals in defaults.items():
            t["stages"][s].update(vals)
            # Any stage that's been dispatched at least once (i.e. not "not_started")
            # carries a current_run; seed run=1 unless the override sets one.
            if (
                t["stages"][s]["status"] != "not_started"
                and t["stages"][s].get("current_run") is None
            ):
                t["stages"][s]["current_run"] = 1
        state.write_task("m", t)
        # Write result.json for each stage in write_results_for so archives work
        for s in write_results_for or []:
            rp = state._result_path("m", s)
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stage": s,
                        "module": "m",
                        "produced_at": "2026-04-22T00:00:00.000000Z",
                        "status": "pass",
                        "artifacts": [],
                        "stage_specific": {},
                    }
                )
            )

    def test_rework_basic(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, write_results_for=["rtl-design", "lint-cdc"])
        result = state.cmd_rework("m", "lint-cdc", "rtl-design", "W415a violation")
        assert result["ok"] is True
        assert result["target_stage"] == "rtl-design"
        # no target_archive in return value (archiving removed from cmd_rework)
        assert "target_archive" not in result
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["freshness"] == "stale"

    def test_rework_target_not_in_staled(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, write_results_for=["rtl-design", "lint-cdc"])
        result = state.cmd_rework("m", "lint-cdc", "rtl-design", "W415a")
        children_stages = {c["stage"] for c in result["staled"]}
        assert "rtl-design" not in children_stages

    def test_rework_cascades_downstream(self, tmp_path, monkeypatch):
        self._setup(
            tmp_path,
            monkeypatch,
            {
                "lint-cdc": {"status": "pass"},
                "simulation": {"status": "pass"},
            },
            write_results_for=["rtl-design", "lint-cdc", "simulation"],
        )
        result = state.cmd_rework("m", "simulation", "rtl-design", "RTL bug")
        children_stages = {c["stage"] for c in result["staled"]}
        assert "lint-cdc" in children_stages
        assert "simulation" in children_stages
        # staled entries are {stage: ...} only — no archive field
        for entry in result["staled"]:
            assert set(entry.keys()) == {"stage"}

    def test_rework_rejects_empty_reason(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        result = state.cmd_rework("m", "lint-cdc", "rtl-design", "")
        assert result["ok"] is False
        assert "reason" in result["error"]

    def test_rework_rejects_whitespace_reason(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        result = state.cmd_rework("m", "lint-cdc", "rtl-design", "  \n  ")
        assert result["ok"] is False

    def test_rework_rejects_not_started_target(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        result = state.cmd_rework("m", "lint-cdc", "simulation", "wrong target")
        assert result["ok"] is False

    def test_rework_rejects_non_ancestor_target(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, {"synthesis": {"status": "pass"}})
        result = state.cmd_rework("m", "lint-cdc", "synthesis", "wrong branch")
        assert result["ok"] is False
        assert "not a DAG ancestor" in result["error"]

    def test_rework_rejects_failed_stage_with_no_current_run(
        self, tmp_path, monkeypatch
    ):
        """failed_stage must have current_run set — otherwise there's no run to
        point rework_trigger at. In production this only happens if Orchestrator mis-uses
        cmd_rework; we reject explicitly so the rework_decision event is well-formed."""
        # rtl-design pass, lint-cdc default (not_started, current_run=None — never dispatched)
        self._setup(tmp_path, monkeypatch, {"lint-cdc": {"status": "not_started"}})
        result = state.cmd_rework("m", "lint-cdc", "rtl-design", "phantom failure")
        assert result["ok"] is False
        assert "current_run" in result["error"]

    def test_rework_event_carries_failed_run(self, tmp_path, monkeypatch):
        """rework_decision event records failed_stage's current_run for audit
        (not used by _find_rework_trigger — canonical is used —
        but the field is retained in the schema for traceability)."""
        # Override default current_run=1 → 7 to verify the value is passed through.
        self._setup(
            tmp_path,
            monkeypatch,
            {
                "lint-cdc": {"status": "fail", "current_run": 7},
            },
            write_results_for=["rtl-design"],
        )
        state.cmd_rework("m", "lint-cdc", "rtl-design", "W415a")
        events = state.read_events("m")
        rd = [e for e in events if e["type"] == "rework_decision"][0]
        assert rd["run"] == 7

    def test_rework_writes_events(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch, write_results_for=["rtl-design", "lint-cdc"])
        state.cmd_rework("m", "lint-cdc", "rtl-design", "W415a")
        events = state.read_events("m")
        rd = [e for e in events if e["type"] == "rework_decision"]
        assert len(rd) == 1
        assert rd[0]["failed_stage"] == "lint-cdc"
        assert rd[0]["target_stage"] == "rtl-design"
        # rework_decision does not contain archive field
        assert "archive" not in rd[0]

    def test_rework_cascade_excludes_target_itself(self, tmp_path, monkeypatch):
        """cascade.staled must not contain target_stage — only downstream."""
        self._setup(tmp_path, monkeypatch, write_results_for=["rtl-design", "lint-cdc"])
        state.cmd_rework("m", "lint-cdc", "rtl-design", "W415a")
        events = state.read_events("m")
        cascades = [e for e in events if e["type"] == "cascade"]
        assert len(cascades) == 1
        cascaded_stages = {c["stage"] for c in cascades[0]["staled"]}
        assert "rtl-design" not in cascaded_stages
        assert "lint-cdc" in cascaded_stages  # fail child IS cascaded

    def test_rework_not_started_children_excluded_from_cascade(
        self, tmp_path, monkeypatch
    ):
        """Children in not_started state are skipped; only pass/fail children cascade."""
        self._setup(
            tmp_path,
            monkeypatch,
            {
                "lint-cdc": {"status": "not_started"},
                "simulation": {"status": "fail"},
            },
            write_results_for=["rtl-design", "simulation"],
        )
        result = state.cmd_rework("m", "simulation", "rtl-design", "RTL logic bug")
        assert result["ok"] is True
        events = state.read_events("m")
        cascades = [e for e in events if e["type"] == "cascade"]
        assert len(cascades) == 1
        cascaded_stages = {c["stage"] for c in cascades[0]["staled"]}
        assert "simulation" in cascaded_stages
        assert "lint-cdc" not in cascaded_stages

    def test_rework_no_cascade_event_when_no_children_need_staling(
        self, tmp_path, monkeypatch
    ):
        """When target's downstream is entirely not_started, no cascade event is written."""
        # target = rtl-design (pass); its children (lint-cdc, simulation) are not_started.
        # failed_stage = simulation — needs a current_run for cmd_rework to record in the
        # rework_decision event; status remains not_started so cascade skips it.
        # (Artificial state for this test; not reachable via valid command sequences.)
        self._setup(
            tmp_path,
            monkeypatch,
            {
                "rtl-design": {"status": "pass"},
                "lint-cdc": {"status": "not_started"},
                "simulation": {"status": "not_started", "current_run": 1},
                "synthesis": {"status": "not_started"},
            },
            write_results_for=["specification", "rtl-design"],
        )
        result = state.cmd_rework("m", "simulation", "rtl-design", "RTL must be re-run")
        assert result["ok"] is True
        assert result["staled"] == []
        events = state.read_events("m")
        assert not any(e["type"] == "cascade" for e in events)

    def test_rework_no_target_archive_in_return(self, tmp_path, monkeypatch):
        """cmd_rework does not archive result.json — target_archive field removed."""
        self._setup(tmp_path, monkeypatch)
        result = state.cmd_rework("m", "lint-cdc", "rtl-design", "W415a")
        assert result["ok"] is True
        # No target_archive in return value
        assert "target_archive" not in result

    def test_rework_twice_idempotent_stale(self, tmp_path, monkeypatch):
        """Reworking the same target twice: second call on stale target is rejected
        (target is stale, not pass/fail/in_progress with clean freshness is fine;
        stale target is still in_progress/stale or pass/stale — allowed since
        status is preserved). Verify rtl-design remains stale after both calls."""
        self._setup(tmp_path, monkeypatch, write_results_for=["rtl-design", "lint-cdc"])
        r1 = state.cmd_rework("m", "lint-cdc", "rtl-design", "first")
        assert r1["ok"] is True
        # After first rework: rtl-design is pass/stale — still allowed as target (status=pass)
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["freshness"] == "stale"
        # Second rework: rtl-design is pass/stale → cmd_rework allows it (status=pass)
        r2 = state.cmd_rework("m", "lint-cdc", "rtl-design", "second")
        assert r2["ok"] is True
        t = state.read_task("m")
        assert t["stages"]["rtl-design"]["freshness"] == "stale"

    def test_rework_event_ts_matches_cascade_ts(self, tmp_path, monkeypatch):
        """rework_decision.ts == cascade.ts (same transaction)."""
        self._setup(
            tmp_path,
            monkeypatch,
            {
                "lint-cdc": {"status": "pass"},
                "simulation": {"status": "fail"},
            },
            write_results_for=["rtl-design", "lint-cdc", "simulation"],
        )
        state.cmd_rework("m", "simulation", "rtl-design", "bug")
        events = state.read_events("m")
        rd = [e for e in events if e["type"] == "rework_decision"][0]
        cas = [e for e in events if e["type"] == "cascade"][0]
        assert rd["ts"] == cas["ts"]

    def test_rework_target_in_progress_now_allowed(self, tmp_path, monkeypatch):
        """cmd_rework target_stage allowed when in_progress (becomes in_progress/stale)."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        task = state.read_task("foo")
        task["stages"]["specification"] = {
            "status": "pass",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [],
        }
        task["stages"]["simulation-plan"] = {
            "status": "in_progress",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [{"run": 1}],
        }
        task["stages"]["simulation"] = {
            "status": "fail",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [],
        }
        state.write_task("foo", task)
        result = state.cmd_rework(
            "foo",
            failed_stage="simulation",
            target_stage="simulation-plan",
            reason="test in_progress target",
        )
        assert result["ok"] is True
        task = state.read_task("foo")
        assert task["stages"]["simulation-plan"]["status"] == "in_progress"
        assert task["stages"]["simulation-plan"]["freshness"] == "stale"

    def test_rework_three_stage_write_order(self, tmp_path, monkeypatch):
        """rework_decision event before write_task; events.jsonl observable post-return."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        task = state.read_task("foo")
        for s in ["specification", "simulation-plan", "rtl-design"]:
            task["stages"][s] = {
                "status": "pass",
                "freshness": "clean",
                "current_run": 1,
                "in_flight": [],
            }
        state.write_task("foo", task)
        state.cmd_rework(
            "foo",
            failed_stage="rtl-design",
            target_stage="simulation-plan",
            reason="test ordering",
        )
        events = state.read_events("foo")
        decisions = [e for e in events if e.get("type") == "rework_decision"]
        assert len(decisions) >= 1
        assert decisions[-1]["failed_stage"] == "rtl-design"
        assert decisions[-1]["target_stage"] == "simulation-plan"
        task = state.read_task("foo")
        assert task["stages"]["simulation-plan"]["freshness"] == "stale"


# ── log command ──


class TestCmdLog:
    def test_log_valid_event(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_log("m", {"type": "debug_dispatch", "module": "m"})
        assert result == {"ok": True}
        events = state.read_events("m")
        assert events[-1]["type"] == "debug_dispatch"
        assert events[-1]["module"] == "m"

    def test_log_rejects_unknown_type(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_log("m", {"type": "unknown_event"})
        assert result["ok"] is False
        assert "unknown" in result["error"]

    def test_log_rejects_auto_event_types(self, tmp_path, monkeypatch):
        """dispatch, outcome, rework_decision, cascade are auto-generated — reject manual logging."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_log("m", {"type": "dispatch", "stage": "rtl-design"})
        assert result["ok"] is False

    def test_log_all_valid_types(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        # escalation requires reason_code+reason — tested separately
        # debug_dispatch requires module
        result = state.cmd_log("m", {"type": "debug_dispatch", "module": "m"})
        assert result == {"ok": True}, "debug_dispatch should be accepted"

    def test_log_escalation_rejects_empty_reason(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_log("m", {"type": "escalation", "reason": ""})
        assert result["ok"] is False
        assert "reason" in result["error"]

    def test_log_escalation_rejects_missing_reason(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_log("m", {"type": "escalation"})
        assert result["ok"] is False

    def test_log_escalation_rejects_whitespace_reason(self, tmp_path, monkeypatch):
        """`reason` must contain at least one non-whitespace character.
        Schema pattern ".*\\S.*" enforces non-empty-after-strip."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # whitespace-only reason should be rejected even with reason_code
        result = state.cmd_log(
            "foo",
            {
                "type": "escalation",
                "reason_code": "test",
                "reason": "   ",
            },
        )
        assert result["ok"] is False
        # And tab/newline-only also rejected
        result = state.cmd_log(
            "foo",
            {
                "type": "escalation",
                "reason_code": "test",
                "reason": "\t\n  ",
            },
        )
        assert result["ok"] is False
        # Sanity: non-whitespace reason still accepted
        ok = state.cmd_log(
            "foo",
            {
                "type": "escalation",
                "reason_code": "test",
                "reason": "real reason",
            },
        )
        assert ok["ok"] is True

    def test_log_escalation_accepts_non_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        result = state.cmd_log(
            "m",
            {
                "type": "escalation",
                "reason_code": "promote_failed_persistent",
                "reason": "promote still failing after retry",
            },
        )
        assert result["ok"] is True

    @pytest.mark.parametrize(
        "etype",
        [
            "ppa_round",
            "ppa_converged",
            "ppa_escalated",
            "power_blocked",
            "plan_enter",
            "plan_exit",
            "plan_review_iteration",
            "simulation-plan_enter",
            "simulation-plan_exit",
            "specification_enter",
            "specification_exit",
        ],
    )
    def test_log_rejects_non_whitelisted_type(self, etype, tmp_path, monkeypatch):
        """cmd_log accepts only the 3 orchestrator types (see test_log_allowed_types_*);
        every other type — including these former event types — is rejected as unknown."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m1")
        res = state.cmd_log("m1", {"type": etype})
        assert res["ok"] is False
        assert "unknown" in res.get("error", "").lower()


# ── CLI integration ──

import subprocess  # noqa: E402


class TestCLI:
    def test_cli_init(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        script = str(
            Path(__file__).resolve().parents[2] / "framework" / "scripts" / "state.py"
        )
        r = subprocess.run(
            [sys.executable, script, "init", "--module", "cli_test"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        output = json.loads(r.stdout)
        assert output["ok"] is True
        assert output["created"] is True

    def test_cli_status(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        script = str(
            Path(__file__).resolve().parents[2] / "framework" / "scripts" / "state.py"
        )
        subprocess.run(
            [sys.executable, script, "init", "--module", "cli_test"],
            capture_output=True,
            cwd=str(tmp_path),
        )
        r = subprocess.run(
            [sys.executable, script, "status", "--module", "cli_test"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0
        output = json.loads(r.stdout)
        assert "module" in output

    def test_cli_reap_rejects_block_reason_flag(self, tmp_path, monkeypatch):
        # argparse rejects the unrecognized --block-reason flag (returncode != 0).
        # Note: since the CLI requires --run, argparse may emit the --run error first
        # or the unrecognized-argument error — either way, exit code must be non-zero.
        monkeypatch.chdir(tmp_path)
        script = str(
            Path(__file__).resolve().parents[2] / "framework" / "scripts" / "state.py"
        )
        r = subprocess.run(
            [
                sys.executable,
                script,
                "reap",
                "--module",
                "any",
                "--stage",
                "rtl-design",
                "--outcome",
                "blocked",
                "--block-reason",
                "legacy",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert r.returncode != 0

    def test_cli_rejects_unknown_stage(self, tmp_path, monkeypatch):
        """argparse `choices=FORWARD_PRIORITY` must reject unknown stage values
        cleanly (exit 2, stderr message), not surface as KeyError stack trace."""
        monkeypatch.chdir(tmp_path)
        script = str(
            Path(__file__).resolve().parents[2] / "framework" / "scripts" / "state.py"
        )
        r = subprocess.run(
            [
                sys.executable,
                script,
                "dispatch",
                "--module",
                "M",
                "--stage",
                "badstage",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert r.returncode == 2  # argparse parse error exit code
        assert "invalid choice" in r.stderr
        assert "badstage" in r.stderr
        assert "Traceback" not in r.stderr  # not a KeyError stack trace

    def test_cli_log_malformed_event_returns_json_envelope(self, tmp_path, monkeypatch):
        """Malformed --event must emit {ok:false, error:...} JSON, not a raw traceback.
        Regression guard: earlier shape let JSONDecodeError propagate uncaught."""
        monkeypatch.chdir(tmp_path)
        script = str(
            Path(__file__).resolve().parents[2] / "framework" / "scripts" / "state.py"
        )
        state.cmd_init("M")
        r = subprocess.run(
            [sys.executable, script, "log", "--module", "M", "--event", "NOT JSON"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        # Convention: error envelope is the signal; exit code stays 0.
        # Stderr must be empty (no traceback).
        assert r.stderr == "", f"unexpected stderr: {r.stderr!r}"
        out = json.loads(r.stdout)
        assert out["ok"] is False
        assert "JSON parse error" in out["error"]

    def test_cli_reap_accepts_reason(self, tmp_path, monkeypatch):
        """CLI reap --outcome blocked --reason requires --run. Use cmd_dispatch to get run."""
        monkeypatch.chdir(tmp_path)
        script = str(
            Path(__file__).resolve().parents[2] / "framework" / "scripts" / "state.py"
        )
        state.cmd_init("cli2")
        # Set specification + simulation-plan pass/clean so rtl-design becomes eligible
        t = state.read_task("cli2")
        t["stages"]["specification"] = {
            "status": "pass",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [],
        }
        t["stages"]["simulation-plan"] = {
            "status": "pass",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [],
        }
        state.write_task("cli2", t)
        # Dispatch rtl-design via cmd_dispatch to get proper run + in_flight
        r_start = state.cmd_dispatch("cli2", "rtl-design")
        assert r_start["ok"]
        run_n = r_start["run"]
        r = subprocess.run(
            [
                sys.executable,
                script,
                "reap",
                "--module",
                "cli2",
                "--stage",
                "rtl-design",
                "--run",
                str(run_n),
                "--outcome",
                "blocked",
                "--reason",
                "no license",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        out = json.loads(r.stdout)
        assert out["action"] == "blocked"


# ── Integration: full forward→fail→rework→pass loop ──


class TestFullLoop:
    _STAGE_SPECIFIC: dict = STAGE_SPECIFIC_MINIMAL

    def test_forward_fail_rework_pass(self, tmp_path, monkeypatch):
        """specification → simulation-plan → rtl-design → lint-cdc (fail) → rework rtl-design → lint-cdc pass."""
        monkeypatch.chdir(tmp_path)
        m = "demo"

        # init
        state.cmd_init(m)

        # specification: start → pass
        r = state.cmd_dispatch(m, "specification")
        assert r["ok"] and r["mode"] == "forward"
        run_specification = r["run"]
        write_run_result(m, "specification", run_specification)
        r = state.cmd_reap(m, "specification", run=run_specification, outcome="pass")
        assert r["action"] == "completed" and r["result_status"] == "pass"

        # simulation-plan: start → pass (rtl-design prereq is simulation-plan)
        r = state.cmd_dispatch(m, "simulation-plan")
        assert r["ok"] and r["mode"] == "forward"
        run_sp = r["run"]
        write_run_result(m, "simulation-plan", run_sp)
        r = state.cmd_reap(m, "simulation-plan", run=run_sp, outcome="pass")
        assert r["action"] == "completed" and r["result_status"] == "pass"

        # rtl-design: start → pass
        r = state.cmd_dispatch(m, "rtl-design")
        assert r["ok"] and r["mode"] == "forward"
        run_rtl_design = r["run"]
        write_run_result(m, "rtl-design", run_rtl_design)
        r = state.cmd_reap(m, "rtl-design", run=run_rtl_design, outcome="pass")
        assert r["action"] == "completed"

        # lint-cdc: start → fail
        r = state.cmd_dispatch(m, "lint-cdc")
        assert r["ok"]
        run_lc1 = r["run"]
        write_run_result(m, "lint-cdc", run_lc1, status="fail")
        r = state.cmd_reap(m, "lint-cdc", run=run_lc1, outcome="fail")
        assert r["result_status"] == "fail"

        # rework: lint-cdc → rtl-design
        r = state.cmd_rework(m, "lint-cdc", "rtl-design", "W415a violation")
        assert r["ok"]
        children_stages = {c["stage"] for c in r["staled"]}
        # rtl-design is the target itself (not cascaded); children may include lint-cdc
        assert "lint-cdc" in children_stages

        # rtl-design rework: start → pass
        # rework_trigger points at the failed lint-cdc canonical result.json
        # (canonical = latest run regardless of pass/fail).
        r = state.cmd_dispatch(m, "rtl-design")
        assert r["mode"] == "rework"
        assert r["rework_trigger"] == "Design/lint-cdc/result.json"
        run_rtl2 = r["run"]
        write_run_result(m, "rtl-design", run_rtl2)
        r = state.cmd_reap(m, "rtl-design", run=run_rtl2, outcome="pass")
        assert r["action"] == "completed"

        # lint-cdc re-run: start → pass
        r = state.cmd_dispatch(m, "lint-cdc")
        assert r["mode"] == "rework"  # stale from cascade
        assert (
            "rework_trigger" not in r
        )  # cascade-stale, no explicit rework targeting lint-cdc
        run_lc2 = r["run"]
        write_run_result(m, "lint-cdc", run_lc2)
        r = state.cmd_reap(m, "lint-cdc", run=run_lc2, outcome="pass")
        assert r["action"] == "completed"

        # Verify final state — four stages pass/clean
        s = state.cmd_status(m)
        for stg in ("specification", "simulation-plan", "rtl-design", "lint-cdc"):
            assert s["stages"][stg]["status"] == "pass"
            assert s["stages"][stg]["freshness"] == "clean"

        # Verify events sequence
        events = state.read_events(m)
        types = [e["type"] for e in events]
        assert "dispatch" in types
        assert "outcome" in types
        assert "rework_decision" in types
        assert "cascade" in types


class TestSimSplitCascadeBehaviors:
    """Key semantic: a pure-RTL rework keeps simulation-plan from being marked stale."""

    def _setup_all_pass(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")
        t = state.read_task("m")
        for s in state.FORWARD_PRIORITY:
            t["stages"][s] = {
                "status": "pass",
                "freshness": "clean",
                "current_run": 1,
                "in_flight": [],
            }
        state.write_task("m", t)
        return t

    def test_rtl_design_cascade_stales_simulation_but_not_simulation_plan(
        self, tmp_path, monkeypatch
    ):
        t = self._setup_all_pass(tmp_path, monkeypatch)
        # use _compute_cascade (pure) + write_task
        state._compute_cascade(t, "rtl-design")
        state.write_task("m", t)
        t = state.read_task("m")
        assert t["stages"]["simulation-plan"]["freshness"] == "clean"
        assert t["stages"]["simulation"]["freshness"] == "stale"

    def test_specification_cascade_stales_simulation_plan(self, tmp_path, monkeypatch):
        t = self._setup_all_pass(tmp_path, monkeypatch)
        # use _compute_cascade (pure) + write_task
        state._compute_cascade(t, "specification")
        state.write_task("m", t)
        t = state.read_task("m")
        assert t["stages"]["simulation-plan"]["freshness"] == "stale"
        assert t["stages"]["simulation"]["freshness"] == "stale"

    def test_rework_simulation_to_simulation_plan_valid(self, tmp_path, monkeypatch):
        self._setup_all_pass(tmp_path, monkeypatch)
        result = state.cmd_rework("m", "simulation", "simulation-plan", "intent gap")
        assert result["ok"] is True
        # simulation-plan is the target itself — it is directly staled (not in cascade list)
        t = state.read_task("m")
        assert t["stages"]["simulation-plan"]["freshness"] == "stale"
        # simulation is a child of simulation-plan and also gets cascaded stale
        staled_stages = {c["stage"] for c in result["staled"]}
        assert "simulation" in staled_stages

    def test_rework_simulation_to_rtl_design_valid(self, tmp_path, monkeypatch):
        self._setup_all_pass(tmp_path, monkeypatch)
        result = state.cmd_rework("m", "simulation", "rtl-design", "RTL bug")
        assert result["ok"] is True

    def test_rework_simulation_plan_to_specification_valid(self, tmp_path, monkeypatch):
        self._setup_all_pass(tmp_path, monkeypatch)
        result = state.cmd_rework(
            "m", "simulation-plan", "specification", "specification ambiguous"
        )
        assert result["ok"] is True

    def test_rework_simulation_plan_to_simulation_plan_rejected_same_stage(
        self, tmp_path, monkeypatch
    ):
        """Same-stage rework is rejected; 'request changes' is handled via an in_progress re-dispatch."""
        self._setup_all_pass(tmp_path, monkeypatch)
        result = state.cmd_rework("m", "simulation-plan", "simulation-plan", "changes")
        assert result["ok"] is False


class TestSchemaValidation:
    """Schema-aware validate_result tests (lint-cdc stage)."""

    def test_validate_result_lint_cdc_valid(self, tmp_path, monkeypatch):
        """A well-formed lint-cdc result.json passes the new schema validation."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("M")
        rdir = tmp_path / "asic" / "M" / "Design" / "lint-cdc"
        rdir.mkdir(parents=True)
        (rdir / "result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "lint-cdc",
                    "module": "M",
                    "produced_at": "2026-04-25T00:00:00Z",
                    "status": "pass",
                    "artifacts": [{"path": "Design/lint-cdc/reports/run.log"}],
                    "stage_specific": {
                        "violations": [],
                    },
                }
            )
        )
        valid, err = state.validate_result("M", "lint-cdc")
        assert valid, f"expected valid, got error: {err}"

    def test_validate_result_lint_cdc_missing_violations_field(
        self, tmp_path, monkeypatch
    ):
        """Missing required stage_specific.violations is rejected with a path-bearing reason."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("M")
        rdir = tmp_path / "asic" / "M" / "Design" / "lint-cdc"
        rdir.mkdir(parents=True)
        (rdir / "result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "lint-cdc",
                    "module": "M",
                    "produced_at": "2026-04-25T00:00:00Z",
                    "status": "pass",
                    "artifacts": [],
                    "stage_specific": {},
                }
            )
        )
        valid, err = state.validate_result("M", "lint-cdc")
        assert valid is False
        assert "violations" in err, f"expected 'violations' in error, got: {err}"

    def test_validate_result_lint_cdc_wrong_severity(self, tmp_path, monkeypatch):
        """A violation with a non-enum severity is rejected with a path indicating the bad value."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("M")
        rdir = tmp_path / "asic" / "M" / "Design" / "lint-cdc"
        rdir.mkdir(parents=True)
        (rdir / "result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "lint-cdc",
                    "module": "M",
                    "produced_at": "2026-04-25T00:00:00Z",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {
                        "violations": [
                            {
                                "id": "V1",
                                "rule": "R1",
                                "severity": "critical",
                                "reason": "x",
                            }
                        ],
                    },
                }
            )
        )
        valid, err = state.validate_result("M", "lint-cdc")
        assert valid is False
        assert "severity" in err, f"expected 'severity' in error, got: {err}"

    def test_validate_result_module_mismatch_still_caught(self, tmp_path, monkeypatch):
        """The runtime module-identity check (not expressible in static schema) still runs."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("M")
        rdir = tmp_path / "asic" / "M" / "Design" / "lint-cdc"
        rdir.mkdir(parents=True)
        (rdir / "result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "lint-cdc",
                    "module": "OTHER",
                    "produced_at": "2026-04-25T00:00:00Z",
                    "status": "pass",
                    "artifacts": [],
                    "stage_specific": {
                        "violations": [],
                    },
                }
            )
        )
        valid, err = state.validate_result("M", "lint-cdc")
        assert valid is False
        assert "module" in err.lower(), f"expected module mismatch error, got: {err}"

    @pytest.mark.parametrize(
        "stage,result_dir,stage_specific",
        [
            (
                "specification",
                ("Design", "specification"),
                {
                    "top_module": "M",
                    "ppa_targets": [],
                },
            ),
            ("rtl-design", ("Design", "rtl-design"), {}),
            ("simulation-plan", ("Verification", "simulation-plan"), {}),
            (
                "simulation",
                ("Verification", "simulation"),
                {},
            ),
            (
                "synthesis",
                ("Design", "synthesis"),
                {
                    "ppa_actual": [{"dim": "area_um2", "value": 1000.0}],
                },
            ),
            (
                "power-analysis",
                ("Verification", "power-analysis"),
                {
                    "saif_artifacts": [
                        {
                            "id": "S1",
                            "saif_path": "saif/S1.saif",
                            "canonical_path": "saif/_dedup/test_a.saif",
                            "format": "saif",
                            "corner_intent": "TT",
                            "sequence_ref": "test_a",
                            "duration_cycles": 1000,
                            "size_bytes": 13132,
                        }
                    ],
                    "compile_info": {
                        "vcs_version": "L-2016.06_Full64",
                    },
                    "failures": [],
                    "ppa_actual": [
                        {
                            "dim": "power_mw",
                            "value": 1.0,
                            "scenario_id": "S1",
                            "source": "reports_ptpx/S1/power_hier.rpt",
                        }
                    ],
                    "violations": [],
                    "power_by_corner": [
                        {
                            "scenario_id": "S1",
                            "power_mw": 1.0,
                            "internal_mw": 0.3,
                            "switching_mw": 0.5,
                            "leakage_mw": 0.2,
                            "toggle_rate": 0.1,
                            "toggle_region": "0ns-1000ns",
                            "corner_intent": "TT",
                            "sequence_ref": "test_a",
                            "analysis_mode": "averaged",
                        }
                    ],
                },
            ),
            (
                "timing-analysis",
                ("Design", "timing-analysis"),
                {
                    "violations": [],
                    "timing": {
                        "setup": {
                            "worst_slack_ns": 2.93,
                            "met": True,
                            "worst_path": "a -> b",
                        },
                        "hold": {
                            "worst_slack_ns": 0.20,
                            "met": True,
                            "worst_path": "c -> d",
                        },
                        "coverage": {
                            "unconstrained_max_delay_endpoints": 0,
                            "register_pins_no_clock": 0,
                        },
                    },
                },
            ),
            ("frontend-signoff", ("frontend-signoff",), {}),
        ],
    )
    def test_validate_result_each_stage_happy_path(
        self, tmp_path, monkeypatch, stage, result_dir, stage_specific
    ):
        """Each per-stage result.schema.json accepts its representative happy-path stage_specific."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("M")
        rdir = tmp_path / "asic" / "M" / Path(*result_dir)
        rdir.mkdir(parents=True)
        (rdir / "result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": stage,
                    "module": "M",
                    "produced_at": "2026-04-25T00:00:00Z",
                    "status": "pass",
                    "artifacts": [],
                    "stage_specific": stage_specific,
                }
            )
        )
        valid, err = state.validate_result("M", stage)
        assert valid, f"{stage}: expected valid, got: {err}"


class TestMultiErrorAggregation:
    def test_format_validation_errors_aggregates_top_3(self):
        """When result.json has multiple schema violations,
        _format_validation_errors aggregates the first 3 errors with
        '+N more' suffix."""
        import jsonschema

        # construct a result.json with 5 missing-required errors
        bad_data = {}  # missing all required fields → many errors
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["a", "b", "c", "d", "e"],
        }
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(
            validator.iter_errors(bad_data), key=lambda e: list(e.absolute_path)
        )
        assert len(errors) >= 5
        formatted = state._format_validation_errors(errors)
        # expect: 3 errors detail + summary line "+2 more"
        assert "+2 more" in formatted
        assert formatted.count("schema violation") == 3


class TestCascadeStaleParallelBranches:
    """DAG: rework rtl-design → cascade through {lint-cdc → synthesis → timing-analysis} ‖ {simulation → power-analysis}
    Converges to frontend-signoff. Each descendant placed stale exactly once."""

    def test_rework_rtl_design_cascades_to_frontend_signoff_via_dual_chains(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # Mark specification/simulation-plan/rtl-design/lint-cdc/synthesis/timing-analysis/simulation/power-analysis all pass/clean
        task = state.read_task("foo")
        for s in [
            "specification",
            "simulation-plan",
            "rtl-design",
            "lint-cdc",
            "synthesis",
            "timing-analysis",
            "simulation",
            "power-analysis",
        ]:
            task["stages"][s] = {
                "status": "pass",
                "freshness": "clean",
                "current_run": 1,
                "in_flight": [],
            }
        state.write_task("foo", task)
        # rework rtl-design from a fictional power-analysis fail
        result = state.cmd_rework(
            "foo",
            failed_stage="power-analysis",
            target_stage="rtl-design",
            reason="test cascade",
        )
        assert result["ok"] is True
        task = state.read_task("foo")
        # rtl-design freshness stale (target itself)
        assert task["stages"]["rtl-design"]["freshness"] == "stale"
        # both chains stale
        for s in [
            "lint-cdc",
            "synthesis",
            "timing-analysis",
            "simulation",
            "power-analysis",
        ]:
            assert task["stages"][s]["freshness"] == "stale", (
                f"{s} should be stale after rework rtl-design"
            )
        # frontend-signoff was not_started, stays not_started (cascade doesn't promote not_started)
        # (or if your test was different, verify according to actual semantics)


class TestCmdInitHardCut:
    def test_init_creates_blank_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = state.cmd_init("foo")
        assert result == {"ok": True, "created": True}
        task = json.loads((tmp_path / "asic" / "foo" / "task.json").read_text())
        for s in state.FORWARD_PRIORITY:
            assert task["stages"][s]["current_run"] is None
            assert task["stages"][s]["in_flight"] == []

    def test_init_idempotent(self, tmp_path, monkeypatch):
        """Re-init on existing task.json must not modify file content."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # Mutate a stage to detect any silent rewrite by second cmd_init
        task_path = tmp_path / "asic" / "foo" / "task.json"
        task = json.loads(task_path.read_text())
        task["stages"]["specification"]["status"] = "in_progress"
        task["stages"]["specification"]["current_run"] = 7
        task_path.write_text(json.dumps(task, indent=2))
        # Second cmd_init: should be idempotent (not overwrite mutation)
        result = state.cmd_init("foo")
        assert result == {"ok": True, "created": False}
        # Verify the mutation was preserved
        task_after = json.loads(task_path.read_text())
        assert task_after["stages"]["specification"]["status"] == "in_progress"
        assert task_after["stages"]["specification"]["current_run"] == 7


class TestEventSchemaValidation:
    def test_append_event_validates_dispatch_shape(self, tmp_path, monkeypatch):
        """append_event must validate the schema before writing a dispatch event."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # A well-formed dispatch event (with all required fields: mode, run, workdir) should write successfully.
        good_event = {
            "type": "dispatch",
            "stage": "specification",
            "mode": "forward",
            "run": 1,
            "workdir": "asic/foo/Design/specification/runs/1/",
        }
        state.append_event("foo", good_event)
        # A dispatch event missing the `mode` field should raise.
        bad_event = {"type": "dispatch", "stage": "specification"}
        with pytest.raises(SystemExit, match="mode"):
            state.append_event("foo", bad_event)

    def test_cmd_log_rejects_unknown_type(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        result = state.cmd_log("foo", {"type": "made_up_type"})
        assert result["ok"] is False

    def test_cmd_log_rejects_state_only_types(self, tmp_path, monkeypatch):
        """`dispatch` / `outcome` / `cascade` / `rework_decision` may be written only by
        state.py itself; they must not be written via cmd_log."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        for forbidden_type in ["dispatch", "outcome", "cascade", "rework_decision"]:
            result = state.cmd_log("foo", {"type": forbidden_type})
            assert result["ok"] is False, f"{forbidden_type} should be rejected"

    def test_cmd_log_accepts_master_types(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # debug_dispatch is allowed.
        ok = state.cmd_log("foo", {"type": "debug_dispatch", "module": "foo"})
        assert ok["ok"] is True
        # escalation is allowed (with required reason_code + reason).
        ok = state.cmd_log(
            "foo",
            {
                "type": "escalation",
                "reason_code": "promote_failed_persistent",
                "reason": "promote still failing after retry",
            },
        )
        assert ok["ok"] is True


class TestEnvelopeSchema:
    def _make_module(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        return state

    def _write_result(self, tmp_path, stage, content):
        # write result.json under the stage's _RESULT_DIR
        rj = tmp_path / state._result_path("foo", stage)
        rj.parent.mkdir(parents=True, exist_ok=True)
        rj.write_text(json.dumps(content))
        return rj

    def test_envelope_artifacts_must_be_objects(self, tmp_path, monkeypatch):
        """Envelope artifacts is array<object{path}>, not array<string>."""
        state = self._make_module(tmp_path, monkeypatch)
        self._write_result(
            tmp_path,
            "specification",
            {
                "schema_version": 1,
                "stage": "specification",
                "module": "foo",
                "produced_at": "2026-04-27T00:00:00Z",
                "status": "pass",
                "artifacts": ["path/to/a.txt"],  # string form (must be rejected)
                "stage_specific": {},
            },
        )
        valid, err = state.validate_result("foo", "specification")
        assert not valid
        # error should reference artifacts shape
        assert "artifacts" in err.lower() or "object" in err.lower()

    def test_envelope_artifacts_object_form_accepted(self, tmp_path, monkeypatch):
        """Properly-shaped artifacts (object array) is accepted at envelope layer.

        Uses lint-cdc which has a simple stage_specific schema (violations[] etc.),
        making this test focused on envelope-level acceptance only."""
        state = self._make_module(tmp_path, monkeypatch)
        self._write_result(
            tmp_path,
            "lint-cdc",
            {
                "schema_version": 1,
                "stage": "lint-cdc",
                "module": "foo",
                "produced_at": "2026-04-27T00:00:00Z",
                "status": "pass",
                "artifacts": [
                    {"path": "lint-cdc/report.html"},
                    {"path": "lint-cdc/cdc.rpt"},
                ],
                "stage_specific": {
                    "violations": [],
                },
            },
        )
        valid, err = state.validate_result("foo", "lint-cdc")
        assert valid, f"envelope should accept object-shape artifacts; err={err}"

    def test_envelope_artifacts_must_not_self_list_result_json(
        self, tmp_path, monkeypatch
    ):
        """artifacts[] must not contain result.json: it is auto-promoted and would
        collide with the canonical result.json during promote. The envelope rejects
        it at validation (left-shift), before promote is ever attempted."""
        state = self._make_module(tmp_path, monkeypatch)
        self._write_result(
            tmp_path,
            "lint-cdc",
            {
                "schema_version": 1,
                "stage": "lint-cdc",
                "module": "foo",
                "produced_at": "2026-04-27T00:00:00Z",
                "status": "pass",
                "artifacts": [{"path": "result.json"}],
                "stage_specific": {"violations": []},
            },
        )
        valid, err = state.validate_result("foo", "lint-cdc")
        assert not valid
        # error renders at $.artifacts[0].path (validator=not)
        assert "artifacts" in err


class TestDAGTopology:
    def test_prereq_of(self):
        assert state.PREREQ_OF == {
            "specification": [],
            "simulation-plan": ["specification"],
            "rtl-design": ["simulation-plan"],
            "lint-cdc": ["rtl-design"],
            "synthesis": ["lint-cdc"],
            "timing-analysis": ["synthesis"],
            "simulation": ["rtl-design"],
            "power-analysis": ["simulation", "timing-analysis"],
            "frontend-signoff": ["power-analysis"],
        }

    def test_forward_priority(self):
        assert state.FORWARD_PRIORITY == [
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

    def test_phase2_chains_converge_at_power_analysis(self):
        """Post-merge: the two Phase-2 chains converge at power-analysis
        (synthesis chain: {lint-cdc, synthesis, timing-analysis}; sim chain: {simulation}).
        power-analysis is the dual-chain join point — its prereqs span both chains
        by design. Downstream (frontend-signoff) is shared tail."""
        chain_a = {"lint-cdc", "synthesis", "timing-analysis"}
        chain_b = {"simulation"}
        # Pre-convergence: each chain depends only on rtl-design or its own members.
        for s in chain_a:
            for p in state.PREREQ_OF[s]:
                assert p == "rtl-design" or p in chain_a, (
                    f"{s} depends on {p} which crosses chain boundary"
                )
        for s in chain_b:
            for p in state.PREREQ_OF[s]:
                assert p == "rtl-design" or p in chain_b, (
                    f"{s} depends on {p} which crosses chain boundary"
                )
        # Convergence point: power-analysis's prereqs span both chain tails.
        assert set(state.PREREQ_OF["power-analysis"]) == {
            "simulation",
            "timing-analysis",
        }


class TestDirectIndexing:
    """task.json read paths use direct dict indexing, not .get(default).

    KeyError on missing required stage fields surfaces malformed task.json
    early rather than silently producing defaults.
    """

    def test_cmd_dispatch_keyerror_on_missing_status(self, tmp_path, monkeypatch):
        """cmd_dispatch directly indexes st['status'] — missing field raises KeyError."""
        monkeypatch.chdir(tmp_path)
        # Hand-craft a pseudo task.json with stage dict missing 'status'
        p = tmp_path / "asic" / "foo" / "task.json"
        p.parent.mkdir(parents=True)
        stages = {
            s: {
                "status": "not_started",
                "freshness": "clean",
                "current_run": None,
                "in_flight": [],
            }
            for s in state.FORWARD_PRIORITY
        }
        # Remove 'status' from specification — simulates malformed task.json
        stages["specification"] = {
            "freshness": "clean",
            "current_run": None,
            "in_flight": [],
        }
        p.write_text(
            json.dumps(
                {
                    "module": "foo",
                    "stages": stages,
                }
            )
        )
        # cmd_dispatch directly indexes st["status"] → KeyError on missing field
        with pytest.raises(KeyError):
            state.cmd_dispatch("foo", "specification")

    def test_cmd_reap_keyerror_on_missing_status(self, tmp_path, monkeypatch):
        """cmd_reap's in_flight check precedes status indexing.

        A stage dict missing 'status' but with valid in_flight=[{run:1}]
        reaches the blocked branch via _non_success_finalize without a
        KeyError on status. The membership check supersedes status access.
        """
        monkeypatch.chdir(tmp_path)
        p = tmp_path / "asic" / "foo" / "task.json"
        p.parent.mkdir(parents=True)
        stages = {
            s: {
                "status": "not_started",
                "freshness": "clean",
                "current_run": None,
                "in_flight": [],
            }
            for s in state.FORWARD_PRIORITY
        }
        # Malformed specification: missing 'status', has in_flight=[{run:1}] and current_run=1
        stages["specification"] = {
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [{"run": 1}],
        }
        p.write_text(
            json.dumps(
                {
                    "module": "foo",
                    "stages": stages,
                }
            )
        )
        # run=1 IS in in_flight → reaches blocked branch → no KeyError on status
        result = state.cmd_reap(
            "foo", "specification", run=1, outcome="blocked", reason="test"
        )
        assert result["action"] == "blocked"


class TestCmdStartBranches:
    def _bootstrap_for_stage(self, tmp_path, monkeypatch, stage):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        bootstrap_prereqs_pass_clean("foo", stage)

    def test_dispatch_returns_run_and_workdir(self, tmp_path, monkeypatch):
        self._bootstrap_for_stage(tmp_path, monkeypatch, "specification")
        result = state.cmd_dispatch("foo", "specification")
        assert result["ok"] is True
        assert result["run"] == 1
        assert result["workdir"] == "asic/foo/Design/specification/runs/1/"
        # workdir physical dir created
        assert (tmp_path / "asic/foo/Design/specification/runs/1").is_dir()

    def test_dispatch_appends_dispatch_event_before_write_task(
        self, tmp_path, monkeypatch
    ):
        """append_event before write_task — events.jsonl is authoritative."""
        self._bootstrap_for_stage(tmp_path, monkeypatch, "specification")
        state.cmd_dispatch("foo", "specification")
        events = state.read_events("foo")
        # last event is dispatch with run + workdir + mode
        assert events[-1]["type"] == "dispatch"
        assert events[-1]["stage"] == "specification"
        assert events[-1]["run"] == 1
        assert events[-1]["workdir"] == "asic/foo/Design/specification/runs/1/"
        assert events[-1]["mode"] == "forward"
        # task.json reflects in_flight + current_run
        task = state.read_task("foo")
        assert task["stages"]["specification"]["current_run"] == 1
        assert task["stages"]["specification"]["in_flight"] == [{"run": 1}]

    def test_dispatch_increments_current_run(self, tmp_path, monkeypatch):
        self._bootstrap_for_stage(tmp_path, monkeypatch, "specification")
        r1 = state.cmd_dispatch("foo", "specification")
        assert r1["run"] == 1
        # Simulate specification re-becoming eligible (manually set to pass/stale)
        task = state.read_task("foo")
        task["stages"]["specification"] = {
            "status": "pass",
            "freshness": "stale",
            "current_run": 1,
            "in_flight": [],
        }
        state.write_task("foo", task)
        # Second start increments run
        r2 = state.cmd_dispatch("foo", "specification")
        assert r2["run"] == 2
        assert r2["workdir"] == "asic/foo/Design/specification/runs/2/"
        assert (tmp_path / "asic/foo/Design/specification/runs/2").is_dir()
        # task.json: in_flight has run 2, current_run = 2
        task = state.read_task("foo")
        assert task["stages"]["specification"]["current_run"] == 2

    def test_dispatch_allows_in_progress_stale_redispatch(self, tmp_path, monkeypatch):
        """in_progress/stale allows multi-run dispatch (simulation case)."""
        self._bootstrap_for_stage(tmp_path, monkeypatch, "simulation")
        # Construct simulation in_progress/stale (simulating cascade hitting running simulation)
        task = state.read_task("foo")
        task["stages"]["simulation"] = {
            "status": "in_progress",
            "freshness": "stale",
            "current_run": 1,
            "in_flight": [{"run": 1}],
        }
        state.write_task("foo", task)
        result = state.cmd_dispatch("foo", "simulation")
        assert result["ok"] is True
        assert result["run"] == 2  # current_run incremented
        # in_flight now has both run 1 (still running) and run 2 (new)
        task = state.read_task("foo")
        assert {"run": 1} in task["stages"]["simulation"]["in_flight"]
        assert {"run": 2} in task["stages"]["simulation"]["in_flight"]

    def test_dispatch_rejects_in_progress_clean(self, tmp_path, monkeypatch):
        self._bootstrap_for_stage(tmp_path, monkeypatch, "specification")
        task = state.read_task("foo")
        task["stages"]["specification"] = {
            "status": "in_progress",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [{"run": 1}],
        }
        state.write_task("foo", task)
        result = state.cmd_dispatch("foo", "specification")
        assert result["ok"] is False


# ── cmd_reap: all branches ──────────────────────────────────


class TestCmdCompleteBranches:
    def _bootstrap_in_progress(self, tmp_path, monkeypatch, stage):
        """Bootstrap prereqs pass/clean + dispatch `stage` (in_progress/clean, run=1)."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        bootstrap_prereqs_pass_clean("foo", stage)
        r = state.cmd_dispatch("foo", stage)
        assert r["ok"], r
        return r

    def _write_valid_result(
        self, tmp_path, stage, run_n, status="pass", stage_specific=None
    ):
        write_run_result(
            "foo", stage, run_n, status=status, stage_specific=stage_specific
        )

    def test_reap_requires_run_keyword(self, tmp_path, monkeypatch):
        """cmd_reap signature must require run as keyword argument (not positional 3rd)."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # Old positional call (module, stage, outcome) should fail
        with pytest.raises(TypeError):
            state.cmd_reap("foo", "specification", "pass")

    def test_reap_ghost_when_run_not_in_in_flight(self, tmp_path, monkeypatch):
        """Run not in in_flight → discarded with reason stale_dispatch; no state change."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # No dispatch happened; run=1 not in in_flight
        result = state.cmd_reap("foo", "specification", run=1, outcome="pass")
        assert result["action"] == "discarded"
        assert result["reason_code"] == "stale_dispatch"
        # task.json status unchanged
        task = state.read_task("foo")
        assert task["stages"]["specification"]["status"] == "not_started"
        # event was appended
        events = state.read_events("foo")
        assert events[-1]["type"] == "outcome"
        assert events[-1]["result_status"] == "discarded"
        assert events[-1]["reason"] == "stale_dispatch"

    def test_reap_superseded_when_run_not_current(self, tmp_path, monkeypatch):
        """Run in in_flight but != current_run → discarded with reason superseded_run."""
        self._bootstrap_in_progress(tmp_path, monkeypatch, "simulation")
        # Cascade hits simulation → in_progress/stale → re-dispatch run 2
        task = state.read_task("foo")
        task["stages"]["simulation"]["freshness"] = "stale"
        state.write_task("foo", task)
        r2 = state.cmd_dispatch("foo", "simulation")
        assert r2["run"] == 2
        # Now run 1 finishes (late) — should be superseded
        # Write a result.json for run 1 (won't be promoted)
        self._write_valid_result(
            tmp_path,
            "simulation",
            1,
            stage_specific={},
        )
        result = state.cmd_reap("foo", "simulation", run=1, outcome="pass")
        assert result["action"] == "discarded"
        assert result["reason_code"] == "superseded_run"
        # run 1 removed from in_flight; current_run still 2
        task = state.read_task("foo")
        assert task["stages"]["simulation"]["current_run"] == 2
        assert {"run": 1} not in task["stages"]["simulation"]["in_flight"]
        assert {"run": 2} in task["stages"]["simulation"]["in_flight"]

    def test_reap_blocked_canonical_absent_returns_not_started(
        self, tmp_path, monkeypatch
    ):
        """blocked outcome + no canonical → not_started/clean."""
        r = self._bootstrap_in_progress(tmp_path, monkeypatch, "specification")
        result = state.cmd_reap(
            "foo",
            "specification",
            run=r["run"],
            outcome="blocked",
            reason="cannot proceed",
        )
        assert result["action"] == "blocked"
        task = state.read_task("foo")
        assert task["stages"]["specification"]["status"] == "not_started"
        assert task["stages"]["specification"]["freshness"] == "clean"

    def test_reap_invalid_when_schema_fails(self, tmp_path, monkeypatch):
        """Malformed result.json → invalid → not_started/clean."""
        r = self._bootstrap_in_progress(tmp_path, monkeypatch, "lint-cdc")
        # Write malformed result.json in the run directory
        rj = (
            state._result_path("foo", "lint-cdc").parent
            / "runs"
            / str(r["run"])
            / "result.json"
        )
        rj.write_text("{}")  # missing all required fields
        result = state.cmd_reap("foo", "lint-cdc", run=r["run"], outcome="pass")
        assert result["action"] == "invalid"
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "not_started"

    def test_reap_pass_promotes_and_state(self, tmp_path, monkeypatch):
        """Happy path: pass → state pass/clean + canonical result.json exists."""
        r = self._bootstrap_in_progress(tmp_path, monkeypatch, "lint-cdc")
        self._write_valid_result(tmp_path, "lint-cdc", r["run"], status="pass")
        result = state.cmd_reap("foo", "lint-cdc", run=r["run"], outcome="pass")
        assert result["action"] == "completed"
        assert result["result_status"] == "pass"
        # canonical has result.json
        canonical_rj = state._result_path("foo", "lint-cdc")
        assert canonical_rj.exists()
        # state pass/clean
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "pass"
        assert task["stages"]["lint-cdc"]["freshness"] == "clean"
        # run removed from in_flight
        assert {"run": r["run"]} not in task["stages"]["lint-cdc"]["in_flight"]

    def test_reap_fail(self, tmp_path, monkeypatch):
        """Fail outcome → state fail/clean."""
        r = self._bootstrap_in_progress(tmp_path, monkeypatch, "lint-cdc")
        self._write_valid_result(tmp_path, "lint-cdc", r["run"], status="fail")
        result = state.cmd_reap("foo", "lint-cdc", run=r["run"], outcome="fail")
        assert result["action"] == "completed"
        assert result["result_status"] == "fail"
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "fail"
        assert task["stages"]["lint-cdc"]["freshness"] == "clean"

    def test_reap_discarded_when_prereq_changed(self, tmp_path, monkeypatch):
        """Prereq stale during exec → discarded with reason prereq_changed."""
        r = self._bootstrap_in_progress(tmp_path, monkeypatch, "lint-cdc")
        # Stale rtl-design while lint-cdc is running
        task = state.read_task("foo")
        task["stages"]["rtl-design"]["freshness"] = "stale"
        state.write_task("foo", task)
        # Write valid result for lint-cdc run
        self._write_valid_result(tmp_path, "lint-cdc", r["run"])
        result = state.cmd_reap("foo", "lint-cdc", run=r["run"], outcome="pass")
        assert result["action"] == "discarded"
        assert result["reason_code"] == "prereq_changed"
        task = state.read_task("foo")
        # canonical absent → not_started/clean
        assert task["stages"]["lint-cdc"]["status"] == "not_started"

    def test_reap_blocked_with_canonical_pass_returns_pass_stale(
        self, tmp_path, monkeypatch
    ):
        """when canonical has prior pass result.json, non-success
        finalize sets pass/stale (canonical is old, this run didn't promote)."""
        # First, complete lint-cdc successfully so canonical exists
        r1 = self._bootstrap_in_progress(tmp_path, monkeypatch, "lint-cdc")
        self._write_valid_result(tmp_path, "lint-cdc", r1["run"], status="pass")
        result1 = state.cmd_reap("foo", "lint-cdc", run=r1["run"], outcome="pass")
        assert result1["action"] == "completed"
        # Confirm canonical exists
        canonical = state._result_path("foo", "lint-cdc")
        assert canonical.exists()
        # Now stale and re-dispatch lint-cdc
        task = state.read_task("foo")
        task["stages"]["lint-cdc"]["freshness"] = "stale"
        state.write_task("foo", task)
        r2 = state.cmd_dispatch("foo", "lint-cdc")
        assert r2["run"] == 2
        # Run 2 reports blocked (subagent gave up)
        result2 = state.cmd_reap(
            "foo", "lint-cdc", run=r2["run"], outcome="blocked", reason="cannot proceed"
        )
        assert result2["action"] == "blocked"
        # canonical exists → pass/stale (not pass/clean, not not_started)
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "pass"
        assert task["stages"]["lint-cdc"]["freshness"] == "stale"

    def test_reap_blocked_with_canonical_fail_returns_fail_stale(
        self, tmp_path, monkeypatch
    ):
        """_non_success_finalize new branch: canonical.status=fail → fail/stale.

        Because cmd_reap fail goes through promote, canonical can
        contain fail content. blocked/invalid/discarded must derive task
        state from canonical.status, not just existence.
        """
        # First, run 1 fails — canonical now has status=fail
        r1 = self._bootstrap_in_progress(tmp_path, monkeypatch, "lint-cdc")
        self._write_valid_result(tmp_path, "lint-cdc", r1["run"], status="fail")
        result1 = state.cmd_reap("foo", "lint-cdc", run=r1["run"], outcome="fail")
        assert result1["action"] == "completed"
        assert result1["result_status"] == "fail"
        # Verify canonical exists with status=fail
        canonical_rj = state._result_path("foo", "lint-cdc")
        assert canonical_rj.exists()
        assert json.loads(canonical_rj.read_text())["status"] == "fail"
        # task.json says lint-cdc fail/clean
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "fail"
        assert task["stages"]["lint-cdc"]["freshness"] == "clean"
        # Mark stale so cmd_dispatch can re-dispatch (fail/clean alone is not eligible).
        task["stages"]["lint-cdc"]["freshness"] = "stale"
        state.write_task("foo", task)
        # Re-dispatch run 2
        r2 = state.cmd_dispatch("foo", "lint-cdc")
        assert r2["ok"], f"cmd_dispatch failed: {r2}"
        assert r2["run"] == 2
        # Write a valid run-specific result for run 2 (blocked still requires the dir)
        self._write_valid_result(tmp_path, "lint-cdc", r2["run"], status="pass")
        # Run 2 reports blocked
        result2 = state.cmd_reap(
            "foo", "lint-cdc", run=r2["run"], outcome="blocked", reason="user blocked"
        )
        assert result2["action"] == "blocked"
        # New behavior: canonical.status=fail → derive fail/stale (NOT pass/stale).
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "fail"
        assert task["stages"]["lint-cdc"]["freshness"] == "stale"


class TestCmdCompleteCLISmoke:
    def test_cli_reap_requires_run_arg(self, tmp_path, monkeypatch):
        """End-to-end CLI: state.py reap without --run should fail at argparse."""
        import subprocess
        from pathlib import Path

        state_py = (
            Path(__file__).resolve().parents[2] / "framework" / "scripts" / "state.py"
        )
        monkeypatch.chdir(tmp_path)
        result = subprocess.run(
            [
                "python3",
                str(state_py),
                "reap",
                "--module",
                "foo",
                "--stage",
                "specification",
                "--outcome",
                "pass",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        # argparse error mentions --run
        combined = result.stdout + result.stderr
        assert "--run" in combined or "run" in combined.lower()

    def test_cli_reap_derives_without_outcome(self, tmp_path, monkeypatch):
        """End-to-end: `state.py reap` with NO --outcome derives the result from
        the run's result.json."""
        import subprocess
        import sys

        script = str(Path(state.__file__))
        monkeypatch.chdir(tmp_path)
        state.cmd_init("cli3")
        bootstrap_prereqs_pass_clean("cli3", "rtl-design")
        r = state.cmd_dispatch("cli3", "rtl-design")
        assert r["ok"]
        write_run_result("cli3", "rtl-design", r["run"])  # valid pass result.json
        proc = subprocess.run(
            [
                sys.executable,
                script,
                "reap",
                "--module",
                "cli3",
                "--stage",
                "rtl-design",
                "--run",
                str(r["run"]),
            ],  # no --outcome
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"stderr={proc.stderr}"
        out = json.loads(proc.stdout)
        assert out["action"] == "completed"
        assert out["result_status"] == "pass"


class TestCascadeStaleIntoInProgress:
    def test_cascade_marks_in_progress_as_stale(self, tmp_path, monkeypatch):
        """cascade extends to in_progress (becomes in_progress/stale).
        The subagent keeps running but its eventual cmd_reap will go
        through discarded(prereq_changed)."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        # specification/simulation-plan/rtl-design pass; simulation is in_progress (subagent running)
        task = state.read_task("foo")
        for s in ["specification", "simulation-plan", "rtl-design"]:
            task["stages"][s] = {
                "status": "pass",
                "freshness": "clean",
                "current_run": 1,
                "in_flight": [],
            }
        task["stages"]["simulation"] = {
            "status": "in_progress",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [{"run": 1}],
        }
        # power-analysis: simulate a fail/clean state so cmd_rework can record its run
        task["stages"]["power-analysis"] = {
            "status": "fail",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [],
        }
        state.write_task("foo", task)
        # rework rtl-design from the power-analysis fail
        result = state.cmd_rework(
            "foo",
            failed_stage="power-analysis",
            target_stage="rtl-design",
            reason="test cascade into in_progress",
        )
        assert result["ok"] is True
        task = state.read_task("foo")
        # simulation should be in_progress/stale (status preserved, freshness flipped)
        assert task["stages"]["simulation"]["status"] == "in_progress"
        assert task["stages"]["simulation"]["freshness"] == "stale"
        # in_flight preserved (run 1 still running)
        assert task["stages"]["simulation"]["in_flight"] == [{"run": 1}]


class TestComputeCascadePure:
    def test_compute_cascade_no_io(self, tmp_path, monkeypatch):
        """_compute_cascade is a pure function: mutates task in-memory,
        returns staled list, does NOT write to disk."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        task = state.read_task("foo")
        # Set up: rtl-design pass/clean, lint-cdc pass/clean, simulation in_progress
        for s in ["specification", "simulation-plan", "rtl-design", "lint-cdc"]:
            task["stages"][s] = {
                "status": "pass",
                "freshness": "clean",
                "current_run": 1,
                "in_flight": [],
            }
        task["stages"]["simulation"] = {
            "status": "in_progress",
            "freshness": "clean",
            "current_run": 1,
            "in_flight": [{"run": 1}],
        }
        # Call _compute_cascade directly
        staled = state._compute_cascade(task, "rtl-design")
        # Should return both lint-cdc and simulation staled
        staled_stages = {x["stage"] for x in staled}
        assert "lint-cdc" in staled_stages
        assert "simulation" in staled_stages
        # task in-memory mutated
        assert task["stages"]["lint-cdc"]["freshness"] == "stale"
        assert task["stages"]["simulation"]["freshness"] == "stale"
        # But task.json on disk NOT mutated (pure function)
        on_disk_task = json.loads((tmp_path / "asic" / "foo" / "task.json").read_text())
        assert on_disk_task["stages"]["lint-cdc"]["freshness"] == "clean"
        assert on_disk_task["stages"]["simulation"]["freshness"] == "clean"


class TestPromoteFailedRetry:
    def test_reap_promote_failed_then_retry_succeeds(self, tmp_path, monkeypatch):
        """When promote fails, state stays in_progress/clean; run remains in_flight.
        Orchestrator can retry by calling cmd_reap again with the same run."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        bootstrap_prereqs_pass_clean("foo", "lint-cdc")
        r = state.cmd_dispatch("foo", "lint-cdc")
        # Write result.json with non-existent artifact (will trigger promote failure)
        rj_path = (
            state._result_path("foo", "lint-cdc").parent
            / "runs"
            / str(r["run"])
            / "result.json"
        )
        rj_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "lint-cdc",
                    "module": "foo",
                    "produced_at": "2026-04-27T00:00:00Z",
                    "status": "pass",
                    "artifacts": [{"path": "missing.txt"}],  # not actually created
                    "stage_specific": {"violations": []},
                }
            )
        )
        # First cmd_reap pass → promote fails
        result1 = state.cmd_reap("foo", "lint-cdc", run=r["run"], outcome="pass")
        assert result1["action"] == "promote_failed"
        # State stays in_progress/clean, run remains in_flight.
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "in_progress"
        assert task["stages"]["lint-cdc"]["freshness"] == "clean"
        assert {"run": r["run"]} in task["stages"]["lint-cdc"]["in_flight"]
        # Now create the missing artifact + retry
        (rj_path.parent / "missing.txt").write_text("now exists")
        result2 = state.cmd_reap("foo", "lint-cdc", run=r["run"], outcome="pass")
        assert result2["action"] == "completed"
        assert result2["result_status"] == "pass"
        # State now pass/clean
        task = state.read_task("foo")
        assert task["stages"]["lint-cdc"]["status"] == "pass"
        assert task["stages"]["lint-cdc"]["freshness"] == "clean"


# ── Phase 9: PPA Self-check + schema tightening ──


class TestSynthSchemaPPA:
    def test_synthesis_dim_enum_restricted(self, tmp_path, monkeypatch):
        """synthesis ppa_actual.dim limited to area_um2, timing_slack_ns."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        rj = state._result_path("foo", "synthesis")
        rj.parent.mkdir(parents=True, exist_ok=True)
        # Try a ppa_actual with disallowed dim (power_mw)
        rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "synthesis",
                    "module": "foo",
                    "produced_at": "2026-04-27",
                    "status": "pass",
                    "artifacts": [],
                    "stage_specific": {
                        "ppa_actual": [
                            {"dim": "power_mw", "actual": 10.0, "value": 10.0}
                        ]
                    },
                }
            )
        )
        valid, err = state.validate_result("foo", "synthesis")
        assert not valid
        # Error should reference dim or enum
        assert "power_mw" in err or "dim" in err.lower() or "enum" in err.lower()

    def test_synthesis_violations_field_accepted(self, tmp_path, monkeypatch):
        """synthesis violations[] field — when status=fail."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        rj = state._result_path("foo", "synthesis")
        rj.parent.mkdir(parents=True, exist_ok=True)
        rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "synthesis",
                    "module": "foo",
                    "produced_at": "2026-04-27",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {
                        "ppa_actual": [{"dim": "timing_slack_ns", "value": -0.12}],
                        "violations": [
                            {"dim": "timing_slack_ns", "target": 0.5, "actual": -0.12}
                        ],
                    },
                }
            )
        )
        valid, err = state.validate_result("foo", "synthesis")
        # If not valid due to other required fields: check err doesn't mention violations
        if not valid:
            assert "violations" not in err.lower(), (
                f"violations field not accepted: {err}"
            )


class TestPowerSchemaPPA:
    def test_power_analysis_dim_enum_restricted(self, tmp_path, monkeypatch):
        """power-analysis ppa_actual.dim limited to power_mw."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        rj = state._result_path("foo", "power-analysis")
        rj.parent.mkdir(parents=True, exist_ok=True)
        rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "power-analysis",
                    "module": "foo",
                    "produced_at": "2026-04-27",
                    "status": "pass",
                    "artifacts": [],
                    "stage_specific": {
                        "ppa_actual": [
                            {
                                "dim": "area_um2",
                                "actual": 100.0,
                                "value": 100.0,
                                "scenario_id": "S1",
                            }
                        ],
                        "power_by_corner": [
                            {
                                "scenario_id": "S1",
                                "power_mw": 1.0,
                                "corner_intent": "TT",
                                "sequence_ref": "test_a",
                            }
                        ],
                    },
                }
            )
        )
        valid, err = state.validate_result("foo", "power-analysis")
        assert not valid

    def test_power_analysis_violations_with_scenario_id_accepted(
        self, tmp_path, monkeypatch
    ):
        """power-analysis violations[] supports scenario_id field."""
        # Schema-content check: violations items allow scenario_id
        schema_path = (
            state._plugin_root() / "skills/power-analysis/references/result.schema.json"
        )
        schema_text = schema_path.read_text()
        assert "violations" in schema_text
        assert "scenario_id" in schema_text
        assert "power_mw" in schema_text

    def test_power_analysis_violations_with_scenario_id_validates(
        self, tmp_path, monkeypatch
    ):
        """validate_result accepts a power-analysis result.json with violations[] containing scenario_id."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        rj = state._result_path("foo", "power-analysis")
        rj.parent.mkdir(parents=True, exist_ok=True)
        rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "power-analysis",
                    "module": "foo",
                    "produced_at": "2026-04-28",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {
                        "ppa_actual": [
                            {"dim": "power_mw", "value": 12.5, "scenario_id": "S1"}
                        ],
                        "power_by_corner": [
                            {
                                "scenario_id": "S1",
                                "power_mw": 12.5,
                                "corner_intent": "TT",
                                "sequence_ref": "test_a",
                            }
                        ],
                        "violations": [
                            {
                                "dim": "power_mw",
                                "target": 10.0,
                                "actual": 12.5,
                                "scenario_id": "S1",
                            }
                        ],
                    },
                }
            )
        )
        valid, err = state.validate_result("foo", "power-analysis")
        # If not valid due to other required fields, violations must not be the cause
        if not valid:
            assert "violations" not in err.lower(), (
                f"violations field with scenario_id should be accepted: {err}"
            )


class TestSpecSchemaPPA:
    def test_specification_ppa_targets_dim_enum(self, tmp_path, monkeypatch):
        """specification ppa_targets.dim is union of {area_um2, timing_slack_ns, power_mw}."""
        # Read schema and verify enum:
        schema_path = (
            state._plugin_root() / "skills/specification/references/result.schema.json"
        )
        schema_text = schema_path.read_text()
        # The dim enum should include all three
        for dim in ["area_um2", "timing_slack_ns", "power_mw"]:
            assert dim in schema_text, (
                f"specification ppa_targets dim enum missing {dim}"
            )


class TestStaSchemaViolations:
    def test_timing_analysis_violations_dim_pattern(self, tmp_path, monkeypatch):
        """timing-analysis violations.dim must match pattern ^timing_..."""
        schema_path = (
            state._plugin_root()
            / "skills/timing-analysis/references/result.schema.json"
        )
        schema_text = schema_path.read_text()
        assert "violations" in schema_text
        assert "timing_[a-z0-9_]" in schema_text

    def test_timing_analysis_violations_invalid_dim_rejected(
        self, tmp_path, monkeypatch
    ):
        """timing-analysis violations with non-timing dim should be rejected by schema."""
        monkeypatch.chdir(tmp_path)
        state.cmd_init("foo")
        rj = state._result_path("foo", "timing-analysis")
        rj.parent.mkdir(parents=True, exist_ok=True)
        rj.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "stage": "timing-analysis",
                    "module": "foo",
                    "produced_at": "2026-04-27",
                    "status": "fail",
                    "artifacts": [],
                    "stage_specific": {
                        "violations": [
                            {"dim": "power_total_mw", "target": 10.0, "actual": 12.0}
                        ]
                    },
                }
            )
        )
        valid, err = state.validate_result("foo", "timing-analysis")
        assert not valid, (
            "power_total_mw should not be valid for timing-analysis violations"
        )


class TestCmdInvalidateStage:
    def _init(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        state.cmd_init("m")

    def _set(self, stage, status, freshness="clean", run=1):
        t = state.read_task("m")
        t["stages"][stage] = {
            "status": status,
            "freshness": freshness,
            "current_run": run,
            "in_flight": [],
        }
        state.write_task("m", t)

    def test_stales_source_itself_and_downstream(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        self._set("specification", "fail")
        self._set("simulation-plan", "pass")  # downstream of specification
        r = state.cmd_invalidate_stage("m", "specification", "brainstorm revised")
        assert r["ok"], r
        t = state.read_task("m")
        # source itself staled, status preserved
        assert t["stages"]["specification"]["freshness"] == "stale"
        assert t["stages"]["specification"]["status"] == "fail"
        # downstream cascaded
        assert t["stages"]["simulation-plan"]["freshness"] == "stale"
        assert any(s["stage"] == "simulation-plan" for s in r["staled"])

    def test_emits_invalidate_event_not_rework(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        self._set("specification", "fail")
        state.cmd_invalidate_stage("m", "specification", "x")
        events = state.read_events("m")
        assert any(
            e["type"] == "invalidate" and e["stage"] == "specification" for e in events
        )
        assert not any(e["type"] == "rework_decision" for e in events)

    def test_rejects_not_started(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        r = state.cmd_invalidate_stage("m", "specification", "x")
        assert not r["ok"]
        assert (
            "can be invalidated" in r["error"]
        )  # anchors the not-run rejection message

    def test_empty_reason_rejected(self, tmp_path, monkeypatch):
        self._init(tmp_path, monkeypatch)
        self._set("specification", "fail")
        r = state.cmd_invalidate_stage("m", "specification", "   ")
        assert not r["ok"]
