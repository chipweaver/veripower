# tests/unit/test_rtl_ledger.py
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/rtl-design/scripts"))
from rtl._ledger import LedgerError, load_ledger, merge_filter  # noqa: E402

_ANN = {"sgdc": {}, "sdc": {}}


def _rec(files):
    return {"files": files, "annotations": _ANN}


def test_merge_overlays_fresh_onto_seeded():
    seeded = {"a": _rec(["a.sv"]), "b": _rec(["b_old.sv"])}
    fresh = {"b": _rec(["b_new.sv"])}
    out = merge_filter(seeded, fresh, ["a", "b"])
    assert out["b"]["files"] == ["b_new.sv"]  # fresh wins
    assert out["a"]["files"] == ["a.sv"]  # untouched carried forward


def test_merge_filters_removed_child_F2():
    # manifest shrank: 'c' is gone from the roster -> evicted from merged ledger
    seeded = {"a": _rec(["a.sv"]), "c": _rec(["c.sv"])}
    out = merge_filter(seeded, {}, ["a"])
    assert "c" not in out
    assert set(out) == {"a"}


def test_load_ledger_ok(tmp_path):
    p = tmp_path / ".child_reports.json"
    p.write_text('{"a": {"files": ["a.sv"], "annotations": {"sgdc": {}, "sdc": {}}}}')
    assert load_ledger(p)["a"]["files"] == ["a.sv"]


def test_load_ledger_raises_on_missing_key_F8(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"a": {"files": ["a.sv"]}}')  # no 'annotations'
    with pytest.raises(LedgerError, match="annotations"):
        load_ledger(p)


def test_load_ledger_raises_on_null_annotation_block(tmp_path):
    # M4: {"sgdc": null, "sdc": null} is key-present but null-valued; it passes a
    # key-only check yet crashes _agg downstream (None.get(...)). The validator must
    # reject it loudly (LedgerError) rather than let a raw AttributeError escape.
    p = tmp_path / "bad.json"
    p.write_text(
        '{"a": {"files": ["a.sv"], "annotations": {"sgdc": null, "sdc": null}}}'
    )
    with pytest.raises(LedgerError, match="sgdc"):
        load_ledger(p)


def test_load_ledger_raises_on_malformed_json_F8(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(LedgerError):
        load_ledger(p)
