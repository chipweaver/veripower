import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/simulation-plan/scripts/validate_plan_review.py"


def _run(tmp_path, doc):
    p = tmp_path / "plan-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(SCRIPT), str(p)], capture_output=True, text=True
    )


def _doc(findings, verdict="concerns", has_critical=False, tps=("TP-1",)):
    return {
        "schema_version": 1,
        "stage": "simulation-plan",
        "module": "m",
        "reviewed_testpoints": list(tps),
        "verdict": verdict,
        "has_critical": has_critical,
        "findings": findings,
    }


def _finding(lens, severity="critical", tp_id="TP-1"):
    return {
        "tp_id": tp_id,
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
    assert "plan-review invalid" in r.stderr


def test_coverage_critical_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("coverage")], has_critical=True))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["flagged"] == [
        {"tp_id": "TP-1", "lens": "coverage", "severity": "critical"}
    ]
    assert v["must_ack"] == []


def test_coverage_important_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("coverage", severity="important")]))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "trip"
    assert v["flagged"] == [
        {"tp_id": "TP-1", "lens": "coverage", "severity": "important"}
    ]
    assert v["must_ack"] == []


def test_adequacy_never_trips_and_is_must_ack(tmp_path):
    r = _run(tmp_path, _doc([_finding("adequacy")], has_critical=True))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "clear"
    assert v["flagged"] == []
    assert v["must_ack"] == [{"tp_id": "TP-1", "severity": "critical"}]


def test_minor_severity_clears(tmp_path):
    r = _run(tmp_path, _doc([_finding("coverage", severity="minor")]))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "clear"
    assert v["flagged"] == []
    assert v["must_ack"] == []


def test_unavailable_only_clears(tmp_path):
    f = {
        "tp_id": "plan",
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
    r = _run(tmp_path, _doc([_finding("coverage")], has_critical=False))
    assert r.returncode == 1
    assert "plan-review inconsistent" in r.stderr


def test_verdict_inconsistent_exit_1(tmp_path):
    r = _run(tmp_path, _doc([_finding("adequacy", severity="important")], verdict="ok"))
    assert r.returncode == 1
    assert "plan-review inconsistent" in r.stderr
