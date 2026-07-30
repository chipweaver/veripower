# tests/unit/test_rtl_review.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"


def _run(tmp_path, doc):
    p = tmp_path / "semantic-review.json"
    p.write_text(json.dumps(doc))
    return subprocess.run(
        ["python3", str(MAIN), "validate-review", "--review", str(p)],
        capture_output=True,
        text=True,
    )


def test_valid_doc_exit_0(tmp_path):
    doc = {
        "stage": "rtl-design",
        "module": "m",
        "findings": [],
    }
    assert _run(tmp_path, doc).returncode == 0


def test_invalid_doc_exit_1_with_stderr(tmp_path):
    doc = {
        "stage": "rtl-design",
        "module": "m",
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
        "stage": "rtl-design",
        "module": "m",
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
        "stage": "rtl-design",
        "module": "m",
        "findings": [
            {"child": "c", "category": "missing", "location": "x", "summary": "y"}
        ],
    }
    r = _run(tmp_path, doc)
    assert r.returncode == 1
    assert "semantic-review invalid" in r.stderr


def test_gating_finding_without_fix_locus_rejected(tmp_path):
    doc = {
        "stage": "rtl-design",
        "module": "m",
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
        "stage": "rtl-design",
        "module": "m",
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
        "stage": "rtl-design",
        "module": "m",
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
        "stage": "rtl-design",
        "module": "m",
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
        "spec_confidence": None,
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
        "stage": "rtl-design",
        "module": "m",
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
        "stage": "rtl-design",
        "module": "m",
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


# ── compute_gate() direct, in-process: the pure reduction finalize reuses without a subprocess ──
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
from rtl import review as vsr  # noqa: E402


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
        "spec_confidence": None,
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
        "spec_confidence": None,
    }


def test_compute_gate_does_not_touch_schema(tmp_path):
    # a BARE doc (no stage/module/...) would crash main()'s schema gate; compute_gate must not.
    assert vsr.compute_gate({"findings": []})["gate"] == "clear"


def test_rtl_review_schema_resolves():
    # review.py lives at scripts/rtl/, one dir deeper than the old script, so
    # _SCHEMA must climb three parents (rtl/ -> scripts/ -> rtl-design/) to reach
    # references/. A wrong dirname count would FileNotFoundError here.
    assert vsr._SCHEMA.is_file()
