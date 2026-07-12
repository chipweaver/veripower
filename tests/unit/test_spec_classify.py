"""spec classify-delta — directive-agnostic first-run/freeze/proceed verdict."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills/specification/scripts"))
from spec import classify  # noqa: E402


def _brainstorm(tmp_path, text="b1"):
    p = tmp_path / "brainstorm.md"
    p.write_text(text, encoding="utf-8")
    return p


def _baseline(tmp_path, *, status, input_digest):
    ss = {"top_module": "m"}
    if input_digest is not None:
        ss["input_digest"] = input_digest
    rj = {"status": status, "stage_specific": ss}
    p = tmp_path / "result.json"
    p.write_text(json.dumps(rj), encoding="utf-8")
    return p


def test_input_digest_is_deterministic_and_content_bound(tmp_path):
    b = _brainstorm(tmp_path, "hello")
    d = classify.input_digest(b)
    assert d == classify.input_digest(b)
    b.write_text("changed", encoding="utf-8")
    assert classify.input_digest(b) != d


def test_no_canonical_result_is_first_run(tmp_path):
    b = _brainstorm(tmp_path)
    assert classify.classify_delta(tmp_path / "nope.json", b)["verdict"] == "first-run"


def test_unchanged_pass_baseline_is_freeze(tmp_path):
    b = _brainstorm(tmp_path)
    cr = _baseline(tmp_path, status="pass", input_digest=classify.input_digest(b))
    assert classify.classify_delta(cr, b)["verdict"] == "freeze"


def test_changed_input_is_proceed(tmp_path):
    b = _brainstorm(tmp_path)
    cr = _baseline(tmp_path, status="pass", input_digest="stale-digest")
    assert classify.classify_delta(cr, b)["verdict"] == "proceed"


def test_failed_baseline_is_proceed(tmp_path):
    b = _brainstorm(tmp_path)
    cr = _baseline(tmp_path, status="fail", input_digest=classify.input_digest(b))
    assert classify.classify_delta(cr, b)["verdict"] == "proceed"


def test_legacy_baseline_without_digest_is_proceed(tmp_path):
    b = _brainstorm(tmp_path)
    cr = _baseline(tmp_path, status="pass", input_digest=None)
    assert classify.classify_delta(cr, b)["verdict"] == "proceed"


def test_none_canonical_result_is_first_run(tmp_path):
    b = _brainstorm(tmp_path)
    assert classify.classify_delta(None, b)["verdict"] == "first-run"


def test_non_dict_canonical_result_is_first_run(tmp_path):
    b = _brainstorm(tmp_path)
    p = tmp_path / "result.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert classify.classify_delta(p, b)["verdict"] == "first-run"
