# tests/unit/test_spec_review.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"


def _run(tmp_path, doc):
    p = tmp_path / "spec-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(MAIN), "validate-review", "--review", str(p)],
        capture_output=True,
        text=True,
    )


def _doc(findings, children=("c",)):
    return {
        "schema_version": 1,
        "stage": "specification",
        "module": "m",
        "reviewed_children": list(children),
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
    r = _run(tmp_path, _doc([]))
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"gate": "clear", "flagged": [], "must_ack": []}


def test_bad_lens_enum_exit_1(tmp_path):
    r = _run(tmp_path, _doc([_finding("bogus")]))
    assert r.returncode == 1
    assert "spec-review invalid" in r.stderr


def test_missing_severity_exit_1(tmp_path):
    bad = {"child": "c", "lens": "faithfulness", "location": "x", "summary": "y"}
    r = _run(tmp_path, _doc([bad]))
    assert r.returncode == 1
    assert "spec-review invalid" in r.stderr


def test_faithfulness_critical_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("faithfulness")]))
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
    assert v["flagged"] == [
        {"child": "c", "lens": "faithfulness", "severity": "important"}
    ]
    assert v["must_ack"] == []


def test_soundness_never_trips_and_is_must_ack(tmp_path):
    # soundness at critical severity is advisory must-acknowledge, never blocks.
    r = _run(tmp_path, _doc([_finding("soundness")]))
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
    r = _run(tmp_path, _doc([f]))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "clear"
    assert v["flagged"] == []
    assert v["must_ack"] == []


def test_mixed_trip_and_must_ack(tmp_path):
    findings = [
        _finding("faithfulness", severity="critical", child="c1"),
        _finding("soundness", severity="important", child="c2"),
    ]
    r = _run(tmp_path, _doc(findings, children=("c1", "c2")))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["flagged"] == [
        {"child": "c1", "lens": "faithfulness", "severity": "critical"}
    ]
    assert v["must_ack"] == [{"child": "c2", "severity": "important"}]


def test_conformance_critical_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("conformance", "critical")]))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["gate"] == "trip"
    assert {"child": "c", "lens": "conformance", "severity": "critical"} in out[
        "flagged"
    ]


def test_conformance_important_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("conformance", "important")]))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["gate"] == "trip"


def test_conformance_minor_does_not_trip(tmp_path):
    r = _run(tmp_path, _doc([_finding("conformance", "minor")]))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["gate"] == "clear"


# ── direct in-process unit tests for the extracted pure gate_verdict() ──
sys.path.insert(0, str(ROOT / "skills" / "specification" / "scripts"))
from spec import review as vsr  # noqa: E402


def test_gate_verdict_clear_on_empty():
    assert vsr.gate_verdict({"findings": []}) == {
        "gate": "clear",
        "flagged": [],
        "must_ack": [],
    }


def test_gate_verdict_faithfulness_critical_trips():
    doc = {
        "findings": [
            {
                "child": "c",
                "lens": "faithfulness",
                "severity": "critical",
                "location": "x",
                "summary": "y",
            }
        ]
    }
    g = vsr.gate_verdict(doc)
    assert g["gate"] == "trip"
    assert g["flagged"] == [
        {"child": "c", "lens": "faithfulness", "severity": "critical"}
    ]
    assert g["must_ack"] == []


def test_gate_verdict_soundness_is_must_ack_not_flagged():
    doc = {
        "findings": [
            {
                "child": "c",
                "lens": "soundness",
                "severity": "critical",
                "location": "x",
                "summary": "y",
            }
        ]
    }
    g = vsr.gate_verdict(doc)
    assert g["gate"] == "clear" and g["flagged"] == []
    assert g["must_ack"] == [{"child": "c", "severity": "critical"}]
