"""Tests for simplan.hints.load_check_hints — the per-child aggregate."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation-plan" / "scripts"))
from simplan.hints import HintsError, load_check_hints  # noqa: E402

CHECK_HINTS = [
    {
        "check_id": "CHK-00",
        "source_feature": "F-00",
        "implementation_detail": "write reg",
        "implementation_detail_verbatim": "reg[addr] <= wdata",
        "brainstorm_anchor": "L12",
        "observable": "rdata",
        "reference_rule": "reg[addr]=wdata",
        "latency": "1",
        "reset_behavior": "0",
    }
]


def _spec(tmp_path, hints=None, children=None):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "m",
                "children": children
                or [{"name": "core", "doc": "core.md", "rtl_modules": ["core"]}],
            }
        )
    )
    hd = tmp_path / "check-hints"
    hd.mkdir(exist_ok=True)
    (hd / "core.json").write_text(json.dumps(CHECK_HINTS if hints is None else hints))
    return tmp_path


def test_hints_are_carried_verbatim(tmp_path):
    # A pure concatenation of what the children authored — no field selection, no tagging.
    # Selecting which fields reach the scaffold is materialize-scaffold's job.
    assert load_check_hints(_spec(tmp_path)) == CHECK_HINTS


def test_pipes_in_a_verbatim_value_need_no_escaping(tmp_path):
    hints = [
        {**CHECK_HINTS[0], "implementation_detail_verbatim": "`sel | in | 3 | bank`"}
    ]
    got = load_check_hints(_spec(tmp_path, hints))
    assert got[0]["implementation_detail_verbatim"] == "`sel | in | 3 | bank`"


def test_aggregates_across_children_in_manifest_order(tmp_path):
    children = [
        {"name": "a", "doc": "a.md", "rtl_modules": ["a"]},
        {"name": "b", "doc": "b.md", "rtl_modules": ["b"]},
    ]
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": children})
    )
    hd = tmp_path / "check-hints"
    hd.mkdir()
    (hd / "a.json").write_text(json.dumps([{**CHECK_HINTS[0], "check_id": "CHK-A"}]))
    (hd / "b.json").write_text(json.dumps([{**CHECK_HINTS[0], "check_id": "CHK-B"}]))
    assert [h["check_id"] for h in load_check_hints(tmp_path)] == ["CHK-A", "CHK-B"]


def test_duplicate_check_id_across_children_raises(tmp_path):
    # Uniqueness is global, which is why the per-child files are aggregated before it is
    # checked: a collision would collapse in a by-id map, making one testpoint appear to
    # cover both and leaving the second silently unverified.
    children = [
        {"name": "a", "doc": "a.md", "rtl_modules": ["a"]},
        {"name": "b", "doc": "b.md", "rtl_modules": ["b"]},
    ]
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": children})
    )
    hd = tmp_path / "check-hints"
    hd.mkdir()
    for c in ("a", "b"):
        (hd / f"{c}.json").write_text(json.dumps(CHECK_HINTS))
    with pytest.raises(HintsError, match="duplicate check_id"):
        load_check_hints(tmp_path)


def test_missing_child_hint_file_raises(tmp_path):
    wd = _spec(tmp_path)
    (wd / "check-hints" / "core.json").unlink()
    with pytest.raises(HintsError, match="check-hints/core.json"):
        load_check_hints(wd)


def test_entry_without_check_id_raises(tmp_path):
    bad = [{k: v for k, v in CHECK_HINTS[0].items() if k != "check_id"}]
    with pytest.raises(HintsError, match="check_id"):
        load_check_hints(_spec(tmp_path, bad))


def test_non_array_hint_file_raises(tmp_path):
    wd = _spec(tmp_path)
    (wd / "check-hints" / "core.json").write_text('{"check_id": "CHK-00"}')
    with pytest.raises(HintsError, match="JSON array"):
        load_check_hints(wd)


def test_empty_children_raises(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"module": "m", "children": []}))
    with pytest.raises(HintsError, match="children"):
        load_check_hints(tmp_path)
