"""Schema-vs-early-fail uniformity.

Lock the if/then-gated pass-only required fields pattern. Without this,
a stage shipping unconditional `required: [ppa_actual]` (or similar
pass-only field) rejects a minimum status=fail result.json, causing
the kernel to mark the run "invalid" and silently swallow the fail signal.

Anchor: 2026-05-10 review round, 3 same-class fixes in 5 days —
synthesis 3250876, timing-analysis b0df23d, power-analysis 357a525.

Locked invariant: every stage's schema accepts the smallest valid
status=fail envelope (envelope-required fields + stage_specific.fail_reason,
+ failure_kind for synthesis/timing-analysis/power-analysis, + failure_phase
for simulation).
"""

import pytest

from framework.scripts import facts, rules

# Stages that require failure_kind in their fail envelope (per route.py's
# failure_kind dispatch — route.py is the sole home of the routing maps).
_FAILURE_KIND_STAGES = {"synthesis", "timing-analysis", "power-analysis"}

# simulation requires failure_phase (which sub-step tripped) alongside fail_reason;
# the schema gates both under if:{status:fail} per skills/simulation/references/result.schema.json.
_FAILURE_PHASE_STAGES = {"simulation"}


@pytest.mark.parametrize("stage", rules.FORWARD_PRIORITY)
def test_schema_validates_minimum_fail_envelope(stage):
    stage_specific = {"fail_reason": "test fail"}
    if stage in _FAILURE_KIND_STAGES:
        stage_specific["failure_kind"] = "infra"
    if stage in _FAILURE_PHASE_STAGES:
        stage_specific["failure_phase"] = "compile"

    result = {
        "schema_version": 1,
        "stage": stage,
        "module": "M",
        "produced_at": "2026-05-12T00:00:00Z",
        "status": "fail",
        "artifacts": [],
        "stage_specific": stage_specific,
    }

    err = facts.validate_result(stage, result)
    assert err is None, f"stage {stage}: minimum status=fail envelope rejected: {err}"


# A status=fail + failure_kind=ppa must additionally carry the measured numbers
# (ppa_actual + violations), per ARCHITECTURE.md §6.2 (uniform across the three
# failure_kind stages). timing-analysis locks its own variant in test_timing_schema.py;
# synthesis + power-analysis are gated here.
_PPA_FAIL_NUMBERS = {
    "synthesis": {
        "ppa_actual": [{"dim": "area_um2", "value": 1234.0}],
        "violations": [{"dim": "area_um2", "target": 1000.0, "actual": 1234.0}],
    },
    "power-analysis": {
        "ppa_actual": [
            {"dim": "power_mw", "value": 12.0, "scenario_id": "s1", "source": "pt"}
        ],
        "violations": [
            {"dim": "power_mw", "target": 10.0, "actual": 12.0, "scenario_id": "s1"}
        ],
    },
}


def _fail_result(stage, stage_specific):
    return {
        "schema_version": 1,
        "stage": stage,
        "module": "M",
        "produced_at": "2026-06-15T00:00:00Z",
        "status": "fail",
        "artifacts": [],
        "stage_specific": stage_specific,
    }


@pytest.mark.parametrize("stage", sorted(_PPA_FAIL_NUMBERS))
def test_ppa_fail_requires_numbers(stage):
    numbers = _PPA_FAIL_NUMBERS[stage]

    # Without the measured numbers, a failure_kind=ppa fail is rejected.
    err = facts.validate_result(
        stage,
        _fail_result(
            stage, {"fail_reason": "PPA gate exceeded", "failure_kind": "ppa"}
        ),
    )
    assert err is not None, (
        f"stage {stage}: ppa fail without ppa_actual/violations accepted"
    )

    # With ppa_actual + violations, it validates.
    err = facts.validate_result(
        stage,
        _fail_result(
            stage,
            {"fail_reason": "PPA gate exceeded", "failure_kind": "ppa", **numbers},
        ),
    )
    assert err is None, f"stage {stage}: ppa fail with numbers rejected: {err}"
