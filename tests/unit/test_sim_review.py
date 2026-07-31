# tests/unit/test_sim_review.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import review  # noqa: E402


def _finding(tp_id="tp1", *, blocking):
    return {
        "tp_id": tp_id,
        "location": "tb/uvm/checker/m_sb.sv:44",
        "blocking": blocking,
        "finding": "compares the pin against itself; TP asked for a prediction",
    }


def _run(tmp_path, doc):
    p = tmp_path / "conformance-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(MAIN), "validate-review", "--review", str(p)],
        capture_output=True,
        text=True,
    )


def test_empty_findings_is_a_clean_review(tmp_path):
    r = _run(tmp_path, {"findings": []})
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip())["gate"] == "clear"


def test_invalid_doc_exit_1(tmp_path):
    # blocking is required and typed: a reviewer that leaves the call out fails the gate
    # rather than defaulting to one side of it.
    bad = {"findings": [{"tp_id": "tp1", "location": "x", "finding": "y"}]}
    r = _run(tmp_path, bad)
    assert r.returncode == 1 and "conformance-review invalid" in r.stderr


def test_the_old_taxonomy_is_rejected(tmp_path):
    # severity/category were the reviewer's call in code words, and a table decoded them.
    # A record still carrying them is a reviewer working from a contract that no longer exists.
    old = {
        "stage": "simulation",
        "module": "m",
        "findings": [
            {
                "tp_id": "tp1",
                "severity": "critical",
                "category": "missing",
                "location": "x",
                "summary": "y",
            }
        ],
    }
    assert _run(tmp_path, old).returncode == 1


def test_gate_is_any_blocking(tmp_path):
    r = _run(tmp_path, {"findings": [_finding(blocking=True)]})
    assert r.returncode == 0, r.stderr
    gate = json.loads(r.stdout.strip())
    assert gate["gate"] == "trip" and gate["flagged"] == ["tp1"]


def test_a_reported_non_blocking_finding_does_not_trip():
    gate = review.compute_gate(
        {"findings": [_finding("tp1", blocking=False), _finding("tp2", blocking=False)]}
    )
    assert gate["gate"] == "clear" and gate["flagged"] == []


def test_one_blocking_finding_among_many_trips():
    gate = review.compute_gate(
        {"findings": [_finding("tp1", blocking=False), _finding("tp2", blocking=True)]}
    )
    assert gate["gate"] == "trip" and gate["flagged"] == ["tp2"]


def test_compute_gate_does_not_touch_schema():
    # callable on a bare findings dict — no schema read
    assert review.compute_gate({"findings": []})["gate"] == "clear"
