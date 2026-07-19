import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation-plan/scripts/simplan/__main__.py"


def _run(tmp_path, doc):
    p = tmp_path / "plan-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(MAIN), "validate-review", "--review", str(p)],
        capture_output=True,
        text=True,
    )


def _doc(findings, tps=("TP-1",)):
    return {
        "schema_version": 1,
        "stage": "simulation-plan",
        "module": "m",
        "reviewed_testpoints": list(tps),
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
    r = _run(tmp_path, _doc([]))
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"gate": "clear", "flagged": [], "must_ack": []}


def test_bad_lens_enum_exit_1(tmp_path):
    r = _run(tmp_path, _doc([_finding("bogus")]))
    assert r.returncode == 1
    assert "plan-review invalid" in r.stderr


def test_coverage_critical_trips(tmp_path):
    r = _run(tmp_path, _doc([_finding("coverage")]))
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
    r = _run(tmp_path, _doc([_finding("adequacy")]))
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
    r = _run(tmp_path, _doc([f]))
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["gate"] == "clear"
    assert v["flagged"] == []
    assert v["must_ack"] == []


# ── extracted pure gate_verdict() (direct import — not subprocess) ───────────
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "simulation-plan" / "scripts"))
from simplan import review as vpr  # noqa: E402


def test_gate_verdict_clear_on_empty():
    assert vpr.gate_verdict({"findings": []}) == {
        "gate": "clear",
        "flagged": [],
        "must_ack": [],
    }


def test_gate_verdict_coverage_critical_trips():
    doc = {
        "findings": [
            {
                "tp_id": "TP-1",
                "lens": "coverage",
                "severity": "critical",
                "location": "x",
                "summary": "y",
            }
        ]
    }
    g = vpr.gate_verdict(doc)
    assert g["gate"] == "trip"
    assert g["flagged"] == [
        {"tp_id": "TP-1", "lens": "coverage", "severity": "critical"}
    ]
    assert g["must_ack"] == []


def test_gate_verdict_adequacy_is_must_ack_only():
    doc = {
        "findings": [
            {
                "tp_id": "TP-1",
                "lens": "adequacy",
                "severity": "critical",
                "location": "x",
                "summary": "y",
            }
        ]
    }
    g = vpr.gate_verdict(doc)
    assert g["gate"] == "clear" and g["flagged"] == []
    assert g["must_ack"] == [{"tp_id": "TP-1", "severity": "critical"}]


def test_schema_resolves():
    # the package is scripts/simplan/, so _SCHEMA needs one extra parent (RV1)
    assert vpr._SCHEMA.is_file()
    assert vpr._SCHEMA.name == "plan-review.schema.json"
