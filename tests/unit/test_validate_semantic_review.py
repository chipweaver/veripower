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
        "schema_version": 2,
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
        "schema_version": 2,
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
        "schema_version": 2,
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
        "schema_version": 2,
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


def test_v1_schema_version_now_rejected(tmp_path):
    doc = {
        "schema_version": 1,  # const is now 2
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "ok",
        "has_critical": False,
        "findings": [],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review invalid" in r.stderr


def test_gating_finding_without_fix_locus_rejected(tmp_path):
    doc = {
        "schema_version": 2,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "concerns",
        "has_critical": True,
        "findings": [
            {
                "child": "c",
                "severity": "critical",
                "category": "missing",
                "location": "x",
                "summary": "y",
            }  # missing fix_locus on a non-unavailable finding
        ],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review invalid" in r.stderr


def test_gating_finding_with_fix_locus_ok(tmp_path):
    doc = {
        "schema_version": 2,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "concerns",
        "has_critical": True,
        "findings": [
            {
                "child": "c",
                "severity": "critical",
                "category": "missing",
                "location": "x",
                "summary": "y",
                "fix_locus": "rtl",
            }
        ],
    }
    assert _run(tmp_path, doc).returncode == 0


def test_bad_fix_locus_enum_rejected(tmp_path):
    doc = {
        "schema_version": 2,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "concerns",
        "has_critical": False,
        "findings": [
            {
                "child": "c",
                "severity": "important",
                "category": "wrong-behavior",
                "location": "x",
                "summary": "y",
                "fix_locus": "plan",  # not in {rtl, spec}
            }
        ],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review invalid" in r.stderr
