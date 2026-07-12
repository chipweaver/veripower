"""rtl classify-delta — directive-agnostic first-run/freeze/proceed over the spec input set."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "skills/rtl-design/scripts"))
from rtl import classify  # noqa: E402


def _spec_dir(tmp_path, design="D", manifest='{"module":"m"}'):
    d = tmp_path / "specification"
    d.mkdir()
    (d / "design.md").write_text(design, encoding="utf-8")
    (d / "manifest.json").write_text(manifest, encoding="utf-8")
    (d / "child_a.md").write_text("CA", encoding="utf-8")
    return d


def _baseline(tmp_path, *, status, input_digest):
    ss = {"top_module": "m"}
    if input_digest is not None:
        ss["input_digest"] = input_digest
    p = tmp_path / "result.json"
    p.write_text(json.dumps({"status": status, "stage_specific": ss}), encoding="utf-8")
    return p


def test_input_digest_deterministic_and_content_bound(tmp_path):
    sd = _spec_dir(tmp_path)
    d = classify.input_digest(sd)
    assert d == classify.input_digest(sd)
    (sd / "child_a.md").write_text("CHANGED", encoding="utf-8")
    assert classify.input_digest(sd) != d


def test_no_canonical_is_first_run(tmp_path):
    sd = _spec_dir(tmp_path)
    assert classify.classify_delta(tmp_path / "nope.json", sd)["verdict"] == "first-run"


def test_unchanged_pass_is_freeze(tmp_path):
    sd = _spec_dir(tmp_path)
    cr = _baseline(tmp_path, status="pass", input_digest=classify.input_digest(sd))
    assert classify.classify_delta(cr, sd)["verdict"] == "freeze"


def test_changed_input_is_proceed(tmp_path):
    sd = _spec_dir(tmp_path)
    cr = _baseline(tmp_path, status="pass", input_digest="stale")
    assert classify.classify_delta(cr, sd)["verdict"] == "proceed"


def test_failed_baseline_is_proceed(tmp_path):
    sd = _spec_dir(tmp_path)
    cr = _baseline(tmp_path, status="fail", input_digest=classify.input_digest(sd))
    assert classify.classify_delta(cr, sd)["verdict"] == "proceed"


def test_none_canonical_result_is_first_run(tmp_path):
    sd = _spec_dir(tmp_path)
    assert classify.classify_delta(None, sd)["verdict"] == "first-run"


def test_non_dict_canonical_result_is_first_run(tmp_path):
    sd = _spec_dir(tmp_path)
    p = tmp_path / "result.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert classify.classify_delta(p, sd)["verdict"] == "first-run"
