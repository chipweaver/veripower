"""Exhaustive routing tests for framework/scripts/route.py.

route() is a pure total function over closed enums, so the whole decision
space is enumerable. Each case asserts both `decision` and `rule`.
"""

import json

import pytest

from framework.scripts import route
from framework.scripts.route import ESCALATE, NEED_INPUT


def test_frontend_signoff_terminal():
    r = route.route("frontend-signoff", fail_reason="x")
    assert r["decision"] == ESCALATE
    assert r["rule"] == "terminal_frontend_signoff"
    assert r["reason_hint"] == "x"


@pytest.mark.parametrize(
    "stage,target",
    [
        ("lint-cdc", "rtl-design"),
        ("simulation-plan", "specification"),
    ],
)
def test_fixed_target(stage, target):
    r = route.route(stage, fail_reason="v")
    assert r["decision"] == target
    assert r["rule"] == f"fixed:{stage}->{target}"
    assert r["reason_hint"] == "v"


def test_simulation_needs_root_cause():
    r = route.route("simulation")
    assert r["decision"] == NEED_INPUT
    assert r["need"] == "root_cause"
    assert r["rule"] == "need_input:root_cause"


def test_simulation_skipped_escalates():
    r = route.route(
        "simulation",
        analysis_state="skipped",
    )
    assert r["decision"] == ESCALATE
    assert r["rule"] == "triage_skipped"


@pytest.mark.parametrize(
    "root_cause,target",
    [
        ("rtl-design", "rtl-design"),
        ("simulation-plan", "simulation-plan"),
        ("specification", "specification"),
        ("simulation", ESCALATE),
    ],
)
def test_simulation_root_cause(root_cause, target):
    r = route.route(
        "simulation",
        root_cause=root_cause,
        analysis_state="complete",
        confidence="high",
    )
    assert r["decision"] == target
    assert r["rule"] == f"triage_root_cause:{root_cause}->{target}"


def test_simulation_high_confidence_routes_to_target():
    r = route.route(
        "simulation", root_cause="rtl-design", analysis_state="complete", confidence="high"
    )
    assert r["decision"] == "rtl-design"


def test_simulation_medium_confidence_escalates_to_operator():
    r = route.route(
        "simulation", root_cause="rtl-design", analysis_state="complete", confidence="medium"
    )
    assert r["decision"] == ESCALATE and r["rule"] == "triage_low_confidence"


def test_simulation_missing_confidence_escalates():
    r = route.route("simulation", root_cause="rtl-design", analysis_state="complete")
    assert r["decision"] == ESCALATE and r["rule"] == "triage_low_confidence"


@pytest.mark.parametrize("stage", ["synthesis", "power-analysis", "timing-analysis"])
def test_infra_escalates(stage):
    r = route.route(stage, failure_kind="infra", fail_reason="lic")
    assert r["decision"] == ESCALATE
    assert r["rule"] == "failure_kind_infra"
    assert r["reason_hint"] == "lic"


@pytest.mark.parametrize(
    "category,target",
    [
        ("netlist", "synthesis"),
        ("sdf", "synthesis"),
        ("tb_uvm", "simulation"),
        ("gls_runtime", "simulation"),
        ("saif_dump", "simulation"),
        ("ptpx_data", "simulation"),
        ("plan", "simulation-plan"),
        ("tooling", ESCALATE),
    ],
)
def test_power_analysis_tooling_category(category, target):
    r = route.route(
        "power-analysis",
        failure_kind="tooling",
        failures=[{"category": category, "error_summary": "e"}],
    )
    assert r["decision"] == target
    assert r["rule"] == f"pa_category:{category}->{target}"
    assert r["reason_hint"] == "e"


@pytest.mark.parametrize("stage", ["synthesis", "timing-analysis"])
def test_syn_timing_tooling_escalates(stage):
    r = route.route(stage, failure_kind="tooling", fail_reason="dc")
    assert r["decision"] == ESCALATE
    assert r["rule"] == "tooling_no_route"


@pytest.mark.parametrize("stage", ["synthesis", "timing-analysis"])
def test_syn_timing_stray_failures_still_escalate(stage):
    # M2 guard: synthesis/timing schemas allow additionalProperties, so a stray
    # failures[] there passes validation — it must NOT route via the pa_category map.
    r = route.route(
        stage,
        failure_kind="tooling",
        failures=[{"category": "gls_runtime", "error_summary": "e"}],
    )
    assert r["decision"] == ESCALATE
    assert r["rule"] == "tooling_no_route"


@pytest.mark.parametrize("stage", ["synthesis", "power-analysis", "timing-analysis"])
def test_ppa_routes_to_rtl(stage):
    r = route.route(stage, failure_kind="ppa", fail_reason="power_mw 12 > 10")
    assert r["decision"] == "rtl-design"
    assert r["rule"] == "ppa->rtl-design"
    assert r["reason_hint"] == "power_mw 12 > 10"


@pytest.mark.parametrize("stage", ["synthesis", "power-analysis", "timing-analysis"])
def test_unrouted_defensive_escalate(stage):
    # L3: unmodeled failure_kind on a PPA stage → defensive ESCALATE, never silent.
    r = route.route(stage, failure_kind=None)
    assert r["decision"] == ESCALATE
    assert r["rule"] == "unrouted"


def test_simulation_unknown_root_cause_escalates():
    # I-1: an unknown root_cause (e.g. schema drift) → named unrouted ESCALATE, not KeyError.
    # confidence="high" clears the confidence gate so this reaches the root_cause check.
    r = route.route(
        "simulation",
        root_cause="nonsense",
        analysis_state="complete",
        confidence="high",
    )
    assert r["decision"] == ESCALATE
    assert r["rule"] == "unrouted:unknown_root_cause"


def test_power_analysis_unknown_category_escalates():
    # I-1: an unknown category → named unrouted ESCALATE, not KeyError.
    r = route.route(
        "power-analysis",
        failure_kind="tooling",
        failures=[{"category": "nonsense", "error_summary": "e"}],
    )
    assert r["decision"] == ESCALATE
    assert r["rule"] == "unrouted:unknown_category"


def test_cli_inputs_from_result_json(tmp_path):
    rj = tmp_path / "result.json"
    rj.write_text(
        json.dumps(
            {
                "stage_specific": {
                    "failure_kind": "tooling",
                    "failures": [
                        {"category": "gls_runtime", "error_summary": "uvm_fatal"}
                    ],
                    "fail_reason": "x",
                }
            }
        )
    )
    got = route._inputs_from_result_json(str(rj))
    assert got == {
        "failure_kind": "tooling",
        "failures": [{"category": "gls_runtime", "error_summary": "uvm_fatal"}],
        "fail_reason": "x",
    }
