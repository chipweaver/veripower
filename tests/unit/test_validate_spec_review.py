import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/specification/scripts/validate_spec_review.py"


def _run(tmp_path, doc):
    p = tmp_path / "spec-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(SCRIPT), str(p)], capture_output=True, text=True
    )


def _doc(findings, verdict="concerns", has_critical=False, children=("c",)):
    return {
        "schema_version": 1,
        "stage": "specification",
        "module": "m",
        "reviewed_children": list(children),
        "verdict": verdict,
        "has_critical": has_critical,
        "findings": findings,
    }


def _finding(lens, severity="critical", child="c"):
    return {
        "child": child,
        "lens": lens,
        "severity": severity,
        "location": "x",
        "summary": "y",
    }


def test_valid_empty_clears(tmp_path):
    r = _run(tmp_path, _doc([], verdict="ok"))
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"gate": "clear", "flagged": [], "must_ack": []}


def test_bad_lens_enum_exit_1(tmp_path):
    r = _run(tmp_path, _doc([_finding("bogus")], has_critical=True))
    assert r.returncode == 1
    assert "spec-review invalid" in r.stderr


def test_missing_severity_exit_1(tmp_path):
    bad = {"child": "c", "lens": "faithfulness", "location": "x", "summary": "y"}
    r = _run(tmp_path, _doc([bad]))
    assert r.returncode == 1
    assert "spec-review invalid" in r.stderr


def test_faithfulness_critical_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("faithfulness")], has_critical=True))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["flagged"] == [
        {"child": "c", "lens": "faithfulness", "severity": "critical"}
    ]
    assert v["must_ack"] == []


def test_faithfulness_important_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("faithfulness", severity="important")]))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["flagged"] == [{"child": "c", "lens": "faithfulness", "severity": "important"}]
    assert v["must_ack"] == []


def test_soundness_never_trips_and_is_must_ack(tmp_path):
    # soundness at critical severity is advisory must-acknowledge, never blocks.
    r = _run(tmp_path, _doc([_finding("soundness")], has_critical=True))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "clear"
    assert v["flagged"] == []
    assert v["must_ack"] == [{"child": "c", "severity": "critical"}]


def test_minor_severity_clears(tmp_path):
    r = _run(tmp_path, _doc([_finding("faithfulness", severity="minor")]))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "clear"
    assert v["flagged"] == []
    assert v["must_ack"] == []


def test_unavailable_only_clears(tmp_path):
    f = {
        "child": "c",
        "lens": "unavailable",
        "severity": "minor",
        "location": "-",
        "summary": "review unavailable: BLOCKED",
    }
    r = _run(tmp_path, _doc([f], verdict="ok"))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "clear"
    assert v["flagged"] == []
    assert v["must_ack"] == []


def test_has_critical_inconsistent_exit_1(tmp_path):
    r = _run(tmp_path, _doc([_finding("faithfulness")], has_critical=False))
    assert r.returncode == 1
    assert "spec-review inconsistent" in r.stderr


def test_verdict_inconsistent_exit_1(tmp_path):
    # a non-unavailable finding requires verdict "concerns"
    r = _run(
        tmp_path, _doc([_finding("soundness", severity="important")], verdict="ok")
    )
    assert r.returncode == 1
    assert "spec-review inconsistent" in r.stderr


def test_mixed_trip_and_must_ack(tmp_path):
    findings = [
        _finding("faithfulness", severity="critical", child="c1"),
        _finding("soundness", severity="important", child="c2"),
    ]
    r = _run(tmp_path, _doc(findings, has_critical=True, children=("c1", "c2")))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["flagged"] == [
        {"child": "c1", "lens": "faithfulness", "severity": "critical"}
    ]
    assert v["must_ack"] == [{"child": "c2", "severity": "important"}]
