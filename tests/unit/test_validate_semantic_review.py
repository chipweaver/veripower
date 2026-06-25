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


def test_gating_finding_without_fix_locus_rejected(tmp_path):
    doc = {
        "schema_version": 1,
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
        "schema_version": 1,
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
        "schema_version": 1,
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


def _gating_doc(fix_locus, *, severity="critical", category="missing"):
    return {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c"],
        "verdict": "concerns",
        "has_critical": severity == "critical",
        "findings": [
            {
                "child": "c",
                "severity": severity,
                "category": category,
                "location": "x",
                "summary": "y",
                "fix_locus": fix_locus,
            }
        ],
    }


def test_gate_trips_rtl_locus(tmp_path):
    r = _run(tmp_path, _gating_doc("rtl"))
    assert r.returncode == 0
    assert json.loads(r.stdout) == {
        "gate": "trip",
        "flagged": [
            {
                "child": "c",
                "category": "missing",
                "severity": "critical",
                "fix_locus": "rtl",
            }
        ],
        "loci": {"rtl": ["c"], "spec": []},
    }


def test_gate_trips_spec_locus(tmp_path):
    r = _run(tmp_path, _gating_doc("spec"))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["loci"] == {"rtl": [], "spec": ["c"]}


def test_gate_trips_on_important_severity(tmp_path):
    r = _run(tmp_path, _gating_doc("rtl", severity="important"))
    assert r.returncode == 0
    assert json.loads(r.stdout)["gate"] == "trip"


def test_gate_clears_on_over_engineering(tmp_path):
    # over-engineering never gates, even at critical severity.
    r = _run(tmp_path, _gating_doc("rtl", category="over-engineering"))
    assert r.returncode == 0
    assert json.loads(r.stdout)["gate"] == "clear"


def test_gate_clears_on_minor_severity(tmp_path):
    r = _run(tmp_path, _gating_doc("rtl", severity="minor"))
    assert r.returncode == 0
    assert json.loads(r.stdout)["gate"] == "clear"


def test_gate_clears_on_unavailable_only(tmp_path):
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
    r = _run(tmp_path, doc)
    assert r.returncode == 0
    assert json.loads(r.stdout)["gate"] == "clear"


def test_mixed_locus_trip_partitions_loci(tmp_path):
    doc = {
        "schema_version": 1,
        "stage": "rtl-design",
        "module": "m",
        "reviewed_children": ["c1", "c2"],
        "verdict": "concerns",
        "has_critical": True,
        "findings": [
            {
                "child": "c1",
                "severity": "critical",
                "category": "missing",
                "location": "x",
                "summary": "y",
                "fix_locus": "rtl",
            },
            {
                "child": "c2",
                "severity": "important",
                "category": "wrong-behavior",
                "location": "z",
                "summary": "w",
                "fix_locus": "spec",
            },
        ],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["loci"] == {"rtl": ["c1"], "spec": ["c2"]}


def test_has_critical_inconsistent_exit_1(tmp_path):
    doc = _gating_doc("rtl", severity="critical")
    doc["has_critical"] = False  # WRONG: a critical finding requires True
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review inconsistent" in r.stderr


def test_verdict_inconsistent_exit_1(tmp_path):
    doc = _gating_doc("rtl", severity="important")
    doc["verdict"] = "ok"  # WRONG: a non-unavailable finding requires "concerns"
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review inconsistent" in r.stderr


# ── compute_gate() direct, in-process — locks the X1 pure-fn extraction (Task 1.5) ───
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
import validate_semantic_review as vsr  # noqa: E402


def test_compute_gate_pure_trip():
    doc = {
        "findings": [
            {
                "child": "c",
                "category": "missing",
                "severity": "critical",
                "fix_locus": "rtl",
            }
        ]
    }
    assert vsr.compute_gate(doc) == {
        "gate": "trip",
        "flagged": [
            {
                "child": "c",
                "category": "missing",
                "severity": "critical",
                "fix_locus": "rtl",
            }
        ],
        "loci": {"rtl": ["c"], "spec": []},
    }


def test_compute_gate_pure_clear_on_over_engineering():
    doc = {
        "findings": [
            {
                "child": "c",
                "category": "over-engineering",
                "severity": "critical",
                "fix_locus": "rtl",
            }
        ]
    }
    assert vsr.compute_gate(doc) == {
        "gate": "clear",
        "flagged": [],
        "loci": {"rtl": [], "spec": []},
    }


def test_compute_gate_does_not_touch_schema(tmp_path):
    # a BARE doc (no schema_version/stage/...) would crash main()'s schema gate; compute_gate must not.
    assert vsr.compute_gate({"findings": []})["gate"] == "clear"
