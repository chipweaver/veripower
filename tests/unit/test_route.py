"""Exhaustive routing tests for framework/scripts/route.py.

route() is a pure total function over closed enums, so the whole decision
space is enumerable. Each case asserts both `decision` and `rule`.
"""

import pytest

from framework.scripts import route
from framework.scripts.route import ESCALATE


def test_frontend_signoff_terminal():
    r = route.route("frontend-signoff", fail_reason="x")
    assert r["decision"] == ESCALATE
    assert r["rule"] == "terminal_frontend_signoff"
    assert r["reason_hint"] == "x"


def test_fixed_target_simulation_plan_only():
    # lint-cdc is NO LONGER fixed-target (moved to input-provenance).
    r = route.route("simulation-plan", fail_reason="v")
    assert r["decision"] == "specification"
    assert r["rule"] == "fixed:simulation-plan->specification"


@pytest.mark.parametrize(
    "category,target",
    [
        ("sgdc_seed", "specification"),
        ("constraint", "specification"),
        ("rtl_cdc", "rtl-design"),
        ("lint_rtl", "rtl-design"),
    ],
)
def test_lint_cdc_input_provenance(category, target):
    r = route.route(
        "lint-cdc",
        failure_kind="tooling",
        failures=[{"category": category, "error_summary": "e"}],
    )
    assert r["decision"] == target
    assert r["rule"] == f"lint_category:{category}->{target}"


def test_lint_cdc_tooling_escalates():
    r = route.route(
        "lint-cdc",
        failure_kind="tooling",
        failures=[{"category": "tooling", "error_summary": "e"}],
    )
    assert r["decision"] == ESCALATE


def test_lint_cdc_unknown_category_escalates():
    r = route.route(
        "lint-cdc", failure_kind="tooling", failures=[{"category": "mystery"}]
    )
    assert r["decision"] == ESCALATE and r["rule"] == "unrouted:unknown_category"


# NOTE: simulation is NOT routed by route() — schedule dispatches simulation-triage and the
# confidence/reliability gate lives in schedule._reliable (kernel._derive_triage uses the
# TRIAGE_ROOT_CAUSE map at reap). route()'s old simulation branch + CLI were dead and removed
# (F-1); those tests moved with the logic (schedule/kernel coverage). The map⊆closure test
# below still exercises TRIAGE_ROOT_CAUSE's legality.


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


def test_power_analysis_unknown_category_escalates():
    # I-1: an unknown category → named unrouted ESCALATE, not KeyError.
    r = route.route(
        "power-analysis",
        failure_kind="tooling",
        failures=[{"category": "nonsense", "error_summary": "e"}],
    )
    assert r["decision"] == ESCALATE
    assert r["rule"] == "unrouted:unknown_category"


def test_route_maps_targets_are_within_failed_rule_input_closure():
    # E6 / §3.4 fix_owner legality: every static failure->target map must only name targets
    # inside the failed rule's TRANSITIVE input closure (kernel.py asserts this in a COMMENT
    # only). A drifted map entry would mint an illegal auto-rebuild target. ESCALATE is exempt.
    from framework.scripts import rules

    maps = {
        "simulation": route.TRIAGE_ROOT_CAUSE,
        "lint-cdc": route.LINT_CATEGORY,
        "power-analysis": route.PA_CATEGORY,
        "simulation-plan": route.FIXED_TARGET,  # {"simulation-plan": "specification"}
    }
    for failed_rule, mapping in maps.items():
        closure = rules.input_closure(failed_rule)
        for key, target in mapping.items():
            if target == ESCALATE:
                continue
            # FIXED_TARGET is keyed by failed_rule, not by a category
            fr = key if failed_rule == "simulation-plan" else failed_rule
            assert target in rules.input_closure(fr), (
                f"{fr} routes to {target!r} which is NOT in its input closure "
                f"{sorted(rules.input_closure(fr))}"
            )
        assert closure  # sanity: the failed rule actually has upstream producers
