# tests/unit/test_rtl_ledger.py
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/rtl-design/scripts"))
from rtl._ledger import LedgerError, load_ledger  # noqa: E402

_ANN = {
    "sgdc": {
        "sync_cell": [],
        "reset_synchronizer": [],
        "set_case_analysis": [],
        "quasi_static": [],
    },
    "sdc": {
        "create_generated_clock": [],
        "set_multicycle_path": [],
        "set_false_path": [],
    },
}


def _rec(files):
    return {"files": files, "annotations": _ANN}


def _write(d, files=None, anns=None):
    """The two sidecars on disk, as the stage authors them."""
    (d / "rtl-files.json").write_text(json.dumps(files if files is not None else {}))
    (d / "constraint-annotations.json").write_text(
        json.dumps(anns if anns is not None else {})
    )
    return d


def test_load_ledger_merges_the_two_sidecars(tmp_path):
    wd = _write(tmp_path, {"a": {"files": ["a.v"]}}, {"a": _ANN})
    got = load_ledger(wd)
    assert got["a"]["files"] == ["a.v"]
    assert got["a"]["annotations"] == _ANN


def test_load_ledger_raises_when_a_sidecar_is_absent(tmp_path):
    import json

    (tmp_path / "rtl-files.json").write_text(json.dumps({"a": {"files": ["a.v"]}}))
    with pytest.raises(LedgerError, match="constraint-annotations.json"):
        load_ledger(tmp_path)


def test_load_ledger_raises_on_roster_disagreement(tmp_path):
    # The two are written together by one verb, so a child in one and not the other is a
    # defect rather than a partial result.
    wd = _write(
        tmp_path, {"a": {"files": ["a.v"]}, "b": {"files": ["b.v"]}}, {"a": _ANN}
    )
    with pytest.raises(LedgerError, match="roster"):
        load_ledger(wd)


def test_load_ledger_raises_on_missing_annotation_category(tmp_path):
    # An omitted category and an explicit [] are not the same claim: the child contract
    # requires every category, so the schema does too.
    lean = {"sgdc": {"sync_cell": []}, "sdc": _ANN["sdc"]}
    wd = _write(tmp_path, {"a": {"files": ["a.v"]}}, {"a": lean})
    with pytest.raises(LedgerError, match="required property"):
        load_ledger(wd)


def test_load_ledger_raises_on_null_annotation_block(tmp_path):
    # M4: null-valued blocks pass a key-only check yet crash _agg downstream.
    wd = _write(tmp_path, {"a": {"files": ["a.v"]}}, {"a": {"sgdc": None, "sdc": None}})
    with pytest.raises(LedgerError, match="not of type 'object'"):
        load_ledger(wd)


def test_load_ledger_raises_on_empty_files_list(tmp_path):
    wd = _write(tmp_path, {"a": {"files": []}}, {"a": _ANN})
    with pytest.raises(LedgerError, match="files"):
        load_ledger(wd)


def test_load_ledger_raises_on_malformed_json(tmp_path):
    wd = _write(tmp_path, {"a": {"files": ["a.v"]}}, {"a": _ANN})
    (wd / "rtl-files.json").write_text("{not json")
    with pytest.raises(LedgerError):
        load_ledger(wd)
