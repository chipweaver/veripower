# tests/unit/test_rtl_cli.py
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"

_VERBS = (
    "check-partition",
    "assemble",
    "validate-review",
    "finalize",
)


def _run(*argv):
    return subprocess.run(["python3", str(MAIN), *argv], capture_output=True, text=True)


def test_cli_help_lists_every_verb():
    r = _run("--help")
    assert r.returncode == 0, r.stderr
    for v in _VERBS:
        assert v in r.stdout, f"{v} missing from --help"


def test_check_conformance_verb_removed(tmp_path):
    # The spec<->RTL presence gate is gone: integration correctness is lint-cdc's
    # elaboration, and the .v/.vh constraint moved into rtl-files.schema.json.
    assert _run("check-conformance", "--workdir", str(tmp_path)).returncode != 0


def test_cli_unknown_verb_exits_2():
    assert _run("bogus").returncode == 2


def test_cli_no_verb_exits_2():
    assert _run().returncode == 2


def test_seed_verb_removed(tmp_path):
    r = _run("seed", "--workdir", str(tmp_path))
    assert r.returncode != 0


def test_semantic_review_accepts_confidence(tmp_path):
    import json

    review = {
        "stage": "rtl-design",
        "module": "m",
        "findings": [
            {
                "child": "c1",
                "severity": "critical",
                "category": "wrong-behavior",
                "location": "c1.v:10",
                "summary": "arb is fixed-prio, §2 wants round-robin",
                "fix_locus": "spec",
                "confidence": "high",
            }
        ],
    }
    p = tmp_path / "semantic-review.json"
    p.write_text(json.dumps(review))
    r = _run("validate-review", "--review", str(p))
    assert r.returncode == 0, r.stderr


# ── finalize's spec_confidence fold (compute_gate direct, in-process) ───────────
import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "skills" / "rtl-design" / "scripts"))
from rtl import review as vsr  # noqa: E402


def _spec_finding(
    child, *, category="wrong-behavior", severity="critical", confidence=None
):
    f = {
        "child": child,
        "category": category,
        "severity": severity,
        "fix_locus": "spec",
    }
    if confidence is not None:
        f["confidence"] = confidence
    return f


def test_finalize_spec_confidence_is_min():
    doc = {
        "findings": [
            _spec_finding("c1", confidence="high"),
            _spec_finding(
                "c2", category="missing", severity="important", confidence="medium"
            ),
        ]
    }
    assert vsr.compute_gate(doc)["spec_confidence"] == "medium"


def test_finalize_spec_confidence_none_without_spec_locus():
    doc = {
        "findings": [
            {
                "child": "c1",
                "category": "wrong-behavior",
                "severity": "critical",
                "fix_locus": "rtl",
            }
        ]
    }
    assert vsr.compute_gate(doc)["spec_confidence"] is None


def test_finalize_spec_confidence_defaults_low_when_missing():
    # confidence omitted on the spec-locus finding -> conservative default "low",
    # which then dominates the min() even against a co-occurring "high".
    doc = {
        "findings": [
            _spec_finding("c1", category="missing", severity="important"),
            _spec_finding("c2", confidence="high"),
        ]
    }
    assert vsr.compute_gate(doc)["spec_confidence"] == "low"
