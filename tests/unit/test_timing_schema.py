"""Schema cases for the timing-analysis structured timing{} block (pass branch)."""

from framework.scripts import facts

_TIMING_OK = {
    "setup": {"worst_slack_ns": 2.93, "met": True, "worst_path": "a -> b"},
    "hold": {"worst_slack_ns": 0.20, "met": True, "worst_path": "c -> d"},
    "coverage": {"output_bits": 4, "output_bits_timed": 4},
}


def _validate(stage_specific, status="pass"):
    result = {
        "stage": "timing-analysis",
        "module": "M",
        "produced_at": "2026-06-08T00:00:00Z",
        "status": status,
        "artifacts": [],
        "stage_specific": stage_specific,
    }
    err = facts.validate_result("timing-analysis", result)
    return err is None, err


def test_pass_with_timing_and_violations_validates():
    valid, err = _validate({"violations": [], "timing": _TIMING_OK})
    assert valid, err


def test_pass_without_timing_rejected():
    valid, _ = _validate({"violations": []})
    assert not valid


def test_pass_without_violations_rejected():
    valid, _ = _validate({"timing": _TIMING_OK})
    assert not valid


def test_infra_fail_without_timing_validates():
    valid, err = _validate(
        {"fail_reason": "PT license missing"},
        status="fail",
    )
    assert valid, err


def test_ppa_fail_with_timing_and_violations_validates():
    valid, err = _validate(
        {
            "fail_reason": "setup/hold timing not met",
            "violations": [
                {
                    "dim": "timing_hold",
                    "target": 0,
                    "actual": -0.005,
                    "path_id": "c -> d",
                }
            ],
            "timing": _TIMING_OK,
        },
        status="fail",
    )
    assert valid, err


def test_ppa_fail_without_timing_rejected():
    valid, _ = _validate(
        {
            "fail_reason": "setup/hold timing not met",
            "violations": [
                {
                    "dim": "timing_hold",
                    "target": 0,
                    "actual": -0.005,
                    "path_id": "c -> d",
                }
            ],
        },
        status="fail",
    )
    assert not valid


def test_tooling_fail_without_timing_validates():
    valid, err = _validate(
        {"fail_reason": "timing-report.txt unparseable"},
        status="fail",
    )
    assert valid, err
