"""Schema-vs-early-fail uniformity.

Lock the if/then-gated pass-only required fields pattern. Without this,
a stage shipping unconditional `required: [ppa_actual]` (or similar
pass-only field) rejects a minimum status=fail result.json, causing
the kernel to mark the run "invalid" and silently swallow the fail signal.

Anchor: 2026-05-10 review round, 3 same-class fixes in 5 days —
synthesis 3250876, timing-analysis b0df23d, power-analysis 357a525.

Locked invariant: every stage's schema accepts the smallest valid
status=fail envelope (envelope-required fields + stage_specific.fail_reason).
Uniformly: no stage asks for a second field on a failure.
"""

import pytest

from framework.scripts import facts, rules


@pytest.mark.parametrize("stage", rules.FORWARD_PRIORITY)
def test_schema_validates_minimum_fail_envelope(stage):
    stage_specific = {"fail_reason": "test fail"}

    result = {
        "stage": stage,
        "module": "M",
        "produced_at": "2026-05-12T00:00:00Z",
        "status": "fail",
        "artifacts": [],
        "stage_specific": stage_specific,
    }

    err = facts.validate_result(stage, result)
    assert err is None, f"stage {stage}: minimum status=fail envelope rejected: {err}"


# A fail that reports a missed requirement must carry the numbers behind it. The claim is
# keyed on the data: carrying requirements[] obliges you to carry the measurements the verdicts
# were judged from. That also fires on a run that judged every row met and still omitted the
# measurements. timing-analysis locks its own variant in test_timing_schema.py; synthesis +
# power-analysis are gated here.
_PPA_FAIL_NUMBERS = {
    "synthesis": {
        "ppa_actual": [{"dim": "area_um2", "value": 1234.0}],
        "requirements": [{"id": "R-1", "met": False, "actual": 1234.0}],
    },
    "power-analysis": {
        "ppa_actual": [
            {"dim": "power_mw", "value": 12.0, "scenario_id": "s1", "source": "pt"}
        ],
        "requirements": [{"id": "R-1", "met": False, "actual": 12.0}],
    },
}


def _fail_result(stage, stage_specific):
    return {
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

    # requirements[] without the measurements they were judged from is rejected.
    err = facts.validate_result(
        stage,
        _fail_result(
            stage,
            {
                "fail_reason": "requirement(s) not met: R-1",
                "requirements": numbers["requirements"],
            },
        ),
    )
    assert err is not None, (
        f"stage {stage}: requirements[] accepted without the measurements behind it"
    )

    # An empty requirements[] obliges them just the same: the gate ran either way.
    err = facts.validate_result(
        stage,
        _fail_result(stage, {"fail_reason": "netlist incomplete", "requirements": []}),
    )
    assert err is not None, (
        f"stage {stage}: an empty requirements[] escaped the obligation"
    )

    # Together they validate.
    err = facts.validate_result(
        stage,
        _fail_result(stage, {"fail_reason": "requirement(s) not met: R-1", **numbers}),
    )
    assert err is None, f"stage {stage}: a fail carrying both rejected: {err}"

    # And an early fail, which carries neither because no gate ran, stays valid.
    err = facts.validate_result(
        stage,
        _fail_result(stage, {"fail_reason": "no license"}),
    )
    assert err is None, f"stage {stage}: early fail rejected: {err}"
