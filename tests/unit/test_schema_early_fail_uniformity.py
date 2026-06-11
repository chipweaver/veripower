"""Schema-vs-early-fail uniformity (charter §4.2 G1).

Lock the if/then-gated pass-only required fields pattern. Without this,
a stage shipping unconditional `required: [ppa_actual]` (or similar
pass-only field) rejects a minimum status=fail result.json, causing
state.py to mark the run "invalid" and silently swallow the fail signal.

Anchor: 2026-05-10 review round, 3 same-class fixes in 5 days —
synthesis 3250876, timing-analysis b0df23d, power-analysis 357a525.

Locked invariant: every stage's schema accepts the smallest valid
status=fail envelope (envelope-required fields + stage_specific.fail_reason,
+ failure_kind for synthesis/timing-analysis/power-analysis, + failure_phase
for simulation).
"""

import json

import pytest

from framework.scripts import state

# Stages that require failure_kind in their fail envelope (per route.py's
# failure_kind dispatch — route.py is the sole home of the routing maps).
_FAILURE_KIND_STAGES = {"synthesis", "timing-analysis", "power-analysis"}

# simulation requires failure_phase (which sub-step tripped) alongside fail_reason;
# the schema gates both under if:{status:fail} per skills/simulation/references/result.schema.json.
_FAILURE_PHASE_STAGES = {"simulation"}


@pytest.mark.parametrize("stage", state.FORWARD_PRIORITY)
def test_schema_validates_minimum_fail_envelope(stage, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state.cmd_init("M")

    rdir = state._result_path("M", stage).parent
    rdir.mkdir(parents=True, exist_ok=True)

    stage_specific = {"fail_reason": "test fail"}
    if stage in _FAILURE_KIND_STAGES:
        stage_specific["failure_kind"] = "infra"
    if stage in _FAILURE_PHASE_STAGES:
        stage_specific["failure_phase"] = "compile"

    (rdir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": stage,
                "module": "M",
                "produced_at": "2026-05-12T00:00:00Z",
                "status": "fail",
                "artifacts": [],
                "stage_specific": stage_specific,
            }
        )
    )

    valid, err = state.validate_result("M", stage)
    assert valid, f"stage {stage}: minimum status=fail envelope rejected: {err}"
