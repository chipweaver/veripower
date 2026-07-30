# tests/unit/test_sim_review.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import review  # noqa: E402


def _doc(findings):
    return {
        "stage": "simulation",
        "module": "m",
        "findings": findings,
    }


def _run(tmp_path, doc):
    p = tmp_path / "conformance-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(MAIN), "validate-review", "--review", str(p)],
        capture_output=True,
        text=True,
    )


def test_valid_doc_exit_0_prints_gate(tmp_path):
    r = _run(tmp_path, _doc([]))
    assert r.returncode == 0, r.stderr
    gate = json.loads(r.stdout.strip())
    assert gate["gate"] == "clear"


def test_invalid_doc_exit_1(tmp_path):
    # a bad severity enum → schema-invalid → exit 1 (the schema gate)
    doc = _doc(
        [
            {
                "tp_id": "tp1",
                "category": "missing",
                "severity": "bogus",
                "location": "x",
                "summary": "x",
            }
        ]
    )
    r = _run(tmp_path, doc)
    assert r.returncode == 1 and "conformance-review invalid" in r.stderr


def test_compute_gate_trips_on_gating_finding():
    gate = review.compute_gate(
        {
            "findings": [
                {"tp_id": "tp1", "category": "wrong-behavior", "severity": "important"}
            ]
        }
    )
    assert gate["gate"] == "trip" and gate["flagged"] == ["tp1"]


def test_compute_gate_advisory_never_trips():
    gate = review.compute_gate(
        {
            "findings": [
                {
                    "tp_id": "tp1",
                    "category": "unverifiable-arch",
                    "severity": "critical",
                },
                {"tp_id": "tp2", "category": "missing", "severity": "minor"},
            ]
        }
    )
    assert gate["gate"] == "clear" and gate["flagged"] == []


def test_compute_gate_does_not_touch_schema():
    # callable on a bare findings dict — no schema read
    assert review.compute_gate({"findings": []})["gate"] == "clear"


def test_schema_resolves(tmp_path):
    # a structurally-valid empty doc validates (proves _SCHEMA path is correct one dir deeper)
    r = _run(tmp_path, _doc([]))
    assert r.returncode == 0, r.stderr
