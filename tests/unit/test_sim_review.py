# tests/unit/test_sim_review.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/simulation/scripts/sim/__main__.py"
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import review  # noqa: E402

_BLOCKING = (
    "## TP-03  tb/uvm/checker/m_sb.sv:49  BLOCKING\n"
    "Compares next_token end to end and probes nothing between; TP-03's intent\n"
    "asks for the per-stage values.\n"
)
_NOTED = (
    "## TP-14  tb/uvm/checker/m_sb.sv:72\n"
    "The aggregate throughput bound is not separately asserted; the per-step\n"
    "bounds are tighter and dominate it.\n"
)


def _run(tmp_path, body):
    p = tmp_path / "conformance-review.md"
    p.write_text("# conformance review — m\n\n" + body)
    r = subprocess.run(
        ["python3", str(MAIN), "validate-review", "--review", str(p)],
        capture_output=True,
        text=True,
    )
    return r, (json.loads(r.stdout) if r.returncode == 0 else None)


def test_a_review_with_nothing_to_report_is_clean(tmp_path):
    r, gate = _run(tmp_path, "")
    assert r.returncode == 0, r.stderr
    assert gate == {"gate": "clear", "flagged": []}


def test_a_reported_finding_without_the_marker_does_not_trip(tmp_path):
    r, gate = _run(tmp_path, _NOTED)
    assert r.returncode == 0, r.stderr
    assert gate["gate"] == "clear"


def test_one_marked_finding_trips_and_names_its_testpoint(tmp_path):
    r, gate = _run(tmp_path, _NOTED + "\n" + _BLOCKING)
    assert r.returncode == 0, r.stderr
    assert gate == {"gate": "trip", "flagged": ["TP-03"]}


def test_the_marker_is_read_off_the_heading_not_the_prose(tmp_path):
    # A finding whose body discusses blocking, or quotes the word, is not thereby blocking:
    # the call is the reviewer's, made in one place, and grep-adjacent prose cannot make it.
    body = (
        "## TP-07  tb/uvm/checker/m_sb.sv:20\n"
        "Worth BLOCKING on if it recurs, but this round the stimulus never reaches it.\n"
    )
    r, gate = _run(tmp_path, body)
    assert r.returncode == 0, r.stderr
    assert gate["gate"] == "clear"


def test_a_location_with_spaces_still_parses(tmp_path):
    body = "## TP-09  plan ref: TP-09 intent, clause 2  BLOCKING\nNo check exists.\n"
    r, gate = _run(tmp_path, body)
    assert r.returncode == 0, r.stderr
    assert gate == {"gate": "trip", "flagged": ["TP-09"]}


def test_missing_file_exits_1(tmp_path):
    r = subprocess.run(
        [
            "python3",
            str(MAIN),
            "validate-review",
            "--review",
            str(tmp_path / "nope.md"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1 and "cannot read" in r.stderr


def test_compute_gate_takes_text(tmp_path):
    assert review.compute_gate("")["gate"] == "clear"
    assert review.compute_gate(_BLOCKING)["flagged"] == ["TP-03"]
