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


# A verdict must name the measurement behind it. The obligation used to be a second array
# (`ppa_actual`) that had to travel beside `requirements[]`; nothing ever read it, and presence
# is not connection — the two were never joined. It is now on the verdict itself, where the
# reader is, and reap carries it into the signoff basis.
_VERDICT_WITHOUT_ITS_MEASUREMENT = {
    "synthesis": [{"id": "R-1", "met": False, "actual": 1234.0}],
    "power-analysis": [{"id": "R-1", "met": False, "actual": 12.0}],
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


@pytest.mark.parametrize("stage", sorted(_VERDICT_WITHOUT_ITS_MEASUREMENT))
def test_a_verdict_without_its_measurement_is_rejected(stage):
    err = facts.validate_result(
        stage,
        _fail_result(
            stage,
            {
                "fail_reason": "requirement(s) not met: R-1",
                "requirements": _VERDICT_WITHOUT_ITS_MEASUREMENT[stage],
            },
        ),
    )
    assert err is not None, (
        f"stage {stage}: a verdict was accepted without naming what it measured"
    )

    # The same verdict, naming what it measured, validates.
    named = [
        {**v, "measured": "area.rpt Total cell area"}
        for v in _VERDICT_WITHOUT_ITS_MEASUREMENT[stage]
    ]
    err = facts.validate_result(
        stage,
        _fail_result(
            stage, {"fail_reason": "requirement(s) not met: R-1", "requirements": named}
        ),
    )
    assert err is None, f"stage {stage}: a named verdict rejected: {err}"

    # And an early fail, which carries neither because no gate ran, stays valid.
    err = facts.validate_result(
        stage,
        _fail_result(stage, {"fail_reason": "no license"}),
    )
    assert err is None, f"stage {stage}: early fail rejected: {err}"
