import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "simulation-triage"
    / "scripts"
    / "validate_analysis.py"
)
SCHEMA = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "simulation-triage"
    / "references"
    / "analysis.schema.json"
)


def _run(payload: dict):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--schema", str(SCHEMA), "--json-stdin"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def test_minimal_complete_only_root_cause_exits_zero():
    """Thin routing layer: complete needs only root_cause (+ analysis_state), no longer groups/recommendations/root_cause_summary."""
    r = _run({"analysis_state": "complete", "root_cause": "rtl-design"})
    assert r.returncode == 0, r.stderr


def test_valid_skipped_exits_zero():
    r = _run(
        {
            "analysis_state": "skipped",
            "skipped_reason": "input incomplete: failure_phase",
        }
    )
    assert r.returncode == 0, r.stderr


def test_missing_analysis_state_exits_nonzero():
    r = _run({"root_cause": "rtl-design"})
    assert r.returncode != 0
    assert "analysis_state" in r.stderr


def test_complete_without_root_cause_exits_nonzero():
    r = _run({"analysis_state": "complete"})
    assert r.returncode != 0
    assert "root_cause" in r.stderr


def test_skipped_without_reason_exits_nonzero():
    r = _run(
        {"analysis_state": "skipped"}
    )  # skipped requires skipped_reason (allOf if/then)
    assert r.returncode != 0
    assert "skipped_reason" in r.stderr


def test_root_cause_outside_enum_exits_nonzero():
    r = _run({"analysis_state": "complete", "root_cause": "synthesis"})
    assert r.returncode != 0


def test_advisory_keys_rejected_by_additional_properties_false():
    """additionalProperties:false — advisory content lives in prose, not stuffed into the routing JSON."""
    payload = {
        "analysis_state": "complete",
        "root_cause": "rtl-design",
        "groups": [
            {
                "fault_type": "x",
                "root_cause_direction": "rtl-design",
                "fix_guidance": "y",
                "regression_level": "targeted",
            }
        ],
    }
    r = _run(payload)
    assert r.returncode != 0
    assert "groups" in r.stderr or "additional" in r.stderr.lower()
