import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-triage/scripts/simtriage/__main__.py"
SCHEMA = ROOT / "skills/simulation-triage/references/analysis.schema.json"


def _run(payload: dict, *, schema=None):
    argv = [sys.executable, str(MAIN), "validate-analysis", "--json-stdin"]
    if schema is not None:
        argv += ["--schema", str(schema)]
    return subprocess.run(
        argv, input=json.dumps(payload), capture_output=True, text=True
    )


def test_default_schema_used_when_flag_omitted():
    r = _run({"analysis_state": "complete", "root_cause": "rtl-design"})
    assert r.returncode == 0, r.stderr


def test_explicit_schema_override_still_accepted():
    r = _run({"analysis_state": "complete", "root_cause": "rtl-design"}, schema=SCHEMA)
    assert r.returncode == 0, r.stderr


def test_minimal_complete_only_root_cause_exits_zero():
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
    r = _run({"analysis_state": "skipped"})
    assert r.returncode != 0
    assert "skipped_reason" in r.stderr


def test_root_cause_outside_enum_exits_nonzero():
    r = _run({"analysis_state": "complete", "root_cause": "synthesis"})
    assert r.returncode != 0


def test_advisory_keys_rejected_by_additional_properties_false():
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


def test_json_file_input(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"analysis_state": "complete", "root_cause": "rtl-design"}))
    r = subprocess.run(
        [sys.executable, str(MAIN), "validate-analysis", "--json-file", str(p)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_invalid_json_exits_nonzero():
    r = subprocess.run(
        [sys.executable, str(MAIN), "validate-analysis", "--json-stdin"],
        input="{not json",
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "not valid JSON" in r.stderr
