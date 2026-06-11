"""Schema cases for the timing-analysis structured timing{} block (pass branch)."""

import json

from framework.scripts import state

_TIMING_OK = {
    "setup": {"worst_slack_ns": 2.93, "met": True, "worst_path": "a -> b"},
    "hold": {"worst_slack_ns": 0.20, "met": True, "worst_path": "c -> d"},
    "coverage": {"unconstrained_max_delay_endpoints": 0, "register_pins_no_clock": 0},
}


def _validate(tmp_path, monkeypatch, stage_specific, status="pass"):
    monkeypatch.chdir(tmp_path)
    state.cmd_init("M")
    rdir = state._result_path("M", "timing-analysis").parent
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": "timing-analysis",
                "module": "M",
                "produced_at": "2026-06-08T00:00:00Z",
                "status": status,
                "artifacts": [],
                "stage_specific": stage_specific,
            }
        )
    )
    return state.validate_result("M", "timing-analysis")


def test_pass_with_timing_and_violations_validates(tmp_path, monkeypatch):
    valid, err = _validate(
        tmp_path, monkeypatch, {"violations": [], "timing": _TIMING_OK}
    )
    assert valid, err


def test_pass_without_timing_rejected(tmp_path, monkeypatch):
    valid, _ = _validate(tmp_path, monkeypatch, {"violations": []})
    assert not valid


def test_pass_without_violations_rejected(tmp_path, monkeypatch):
    valid, _ = _validate(tmp_path, monkeypatch, {"timing": _TIMING_OK})
    assert not valid


def test_infra_fail_without_timing_validates(tmp_path, monkeypatch):
    valid, err = _validate(
        tmp_path,
        monkeypatch,
        {"fail_reason": "PT license missing", "failure_kind": "infra"},
        status="fail",
    )
    assert valid, err


def test_ppa_fail_with_timing_and_violations_validates(tmp_path, monkeypatch):
    valid, err = _validate(
        tmp_path,
        monkeypatch,
        {
            "fail_reason": "setup/hold timing not met",
            "failure_kind": "ppa",
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


def test_ppa_fail_without_timing_rejected(tmp_path, monkeypatch):
    valid, _ = _validate(
        tmp_path,
        monkeypatch,
        {
            "fail_reason": "setup/hold timing not met",
            "failure_kind": "ppa",
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


def test_tooling_fail_without_timing_validates(tmp_path, monkeypatch):
    valid, err = _validate(
        tmp_path,
        monkeypatch,
        {"fail_reason": "timing-report.txt unparseable", "failure_kind": "tooling"},
        status="fail",
    )
    assert valid, err
