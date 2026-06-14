import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/simulation/scripts/validate_conformance_review.py"


def _run(tmp_path, doc):
    p = tmp_path / "conformance-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(SCRIPT), str(p)], capture_output=True, text=True
    )


def test_valid_doc_exit_0(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "simulation",
        "module": "m",
        "reviewed_testpoints": ["TP-1"],
        "verdict": "ok",
        "has_critical": False,
        "findings": [],
    }
    assert _run(tmp_path, doc).returncode == 0


def test_invalid_category_exit_1_with_stderr(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "simulation",
        "module": "m",
        "reviewed_testpoints": ["TP-1"],
        "verdict": "concerns",
        "has_critical": True,
        "findings": [
            {
                "tp_id": "TP-1",
                "severity": "critical",
                "category": "over-engineering",
                "location": "x",
                "summary": "y",
            }
        ],
    }  # over-engineering was removed from the enum (R2 PL4)
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "conformance-review invalid" in r.stderr


def test_unavailable_category_exit_0(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "simulation",
        "module": "m",
        "reviewed_testpoints": [],
        "verdict": "ok",
        "has_critical": False,
        "findings": [
            {
                "tp_id": "-",
                "severity": "minor",
                "category": "unavailable",
                "location": "-",
                "summary": "review (wave) failed: BLOCKED",
            }
        ],
    }
    assert _run(tmp_path, doc).returncode == 0


def test_wrong_stage_exit_1(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_testpoints": [],
        "verdict": "ok",
        "has_critical": False,
        "findings": [],
    }  # stage must be const "simulation"
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "conformance-review invalid" in r.stderr


def test_verdict_inconsistent_exit_1(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "simulation",
        "module": "m",
        "reviewed_testpoints": ["TP-1"],
        "verdict": "ok",  # WRONG: a non-unavailable finding requires "concerns"
        "has_critical": False,
        "findings": [
            {
                "tp_id": "TP-1",
                "severity": "important",
                "category": "missing",
                "location": "x",
                "summary": "y",
            }
        ],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "conformance-review inconsistent" in r.stderr


def test_has_critical_inconsistent_exit_1(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "simulation",
        "module": "m",
        "reviewed_testpoints": ["TP-1"],
        "verdict": "concerns",
        "has_critical": False,  # WRONG: a critical finding requires True
        "findings": [
            {
                "tp_id": "TP-1",
                "severity": "critical",
                "category": "fake-green",
                "location": "x",
                "summary": "y",
            }
        ],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "conformance-review inconsistent" in r.stderr
