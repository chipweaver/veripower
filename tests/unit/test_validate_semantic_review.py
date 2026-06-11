import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/rtl-design/scripts/validate_semantic_review.py"


def _run(tmp_path, doc):
    p = tmp_path / "semantic-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(SCRIPT), str(p)], capture_output=True, text=True
    )


def test_valid_doc_exit_0(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "ok",
        "has_critical": False,
        "findings": [],
    }
    assert _run(tmp_path, doc).returncode == 0


def test_invalid_doc_exit_1_with_stderr(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "concerns",
        "has_critical": False,
        "findings": [
            {
                "child": "c",
                "severity": "blocker",
                "category": "missing",
                "location": "x",
                "summary": "y",
            }
        ],
    }  # bad severity enum
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review invalid" in r.stderr


def test_unavailable_category_exit_0(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "ok",
        "has_critical": False,
        "findings": [
            {
                "child": "c",
                "severity": "minor",
                "category": "unavailable",
                "location": "-",
                "summary": "review unavailable: BLOCKED",
            }
        ],
    }
    assert _run(tmp_path, doc).returncode == 0


def test_missing_severity_exit_1(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "concerns",
        "has_critical": False,
        "findings": [
            {"child": "c", "category": "missing", "location": "x", "summary": "y"}
        ],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review invalid" in r.stderr
