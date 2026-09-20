# tests/unit/test_rtl_ledger.py
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/rtl-design/scripts"))
from rtl.result import RTLInputError, read_rtl_inputs  # noqa: E402

ANN = {
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


def write_rtl_inputs(d, files=None, anns=None):
    """The two sidecars on disk, as the stage authors them."""
    (d / "rtl-files.json").write_text(json.dumps(files if files is not None else {}))
    (d / "constraint-annotations.json").write_text(
        json.dumps(anns if anns is not None else {})
    )
    return d


def test_read_rtl_inputs_validates_sidecars_and_returns_compilation_inputs(tmp_path):
    wd = write_rtl_inputs(tmp_path, {"files": ["src/a.v"]}, {"a": ANN})
    got = read_rtl_inputs(wd)
    assert got == {"files": ["src/a.v"]}


def test_read_rtl_inputs_raises_when_a_sidecar_is_absent(tmp_path):
    import json

    (tmp_path / "rtl-files.json").write_text(json.dumps({"files": ["src/a.v"]}))
    with pytest.raises(RTLInputError, match="constraint-annotations.json"):
        read_rtl_inputs(tmp_path)


def test_file_order_is_independent_of_annotation_owners(tmp_path):
    files = {"files": ["src/base.sv", "src/derived.sv", "src/top.sv"]}
    wd = write_rtl_inputs(tmp_path, files, {"implementation": ANN})
    assert read_rtl_inputs(wd) == files


def test_read_rtl_inputs_raises_on_missing_annotation_category(tmp_path):
    # An omitted category and an explicit [] are not the same claim: the child contract
    # requires every category, so the schema does too.
    lean = {"sgdc": {"sync_cell": []}, "sdc": ANN["sdc"]}
    wd = write_rtl_inputs(tmp_path, {"files": ["src/a.v"]}, {"a": lean})
    with pytest.raises(RTLInputError, match="required property"):
        read_rtl_inputs(wd)


def test_read_rtl_inputs_raises_on_null_annotation_block(tmp_path):
    # Null-valued blocks pass a key-only check yet crash _agg downstream.
    wd = write_rtl_inputs(
        tmp_path, {"files": ["src/a.v"]}, {"a": {"sgdc": None, "sdc": None}}
    )
    with pytest.raises(RTLInputError, match="not of type 'object'"):
        read_rtl_inputs(wd)


def test_read_rtl_inputs_raises_on_empty_files_list(tmp_path):
    wd = write_rtl_inputs(tmp_path, {"files": []}, {"a": ANN})
    with pytest.raises(RTLInputError, match="files"):
        read_rtl_inputs(wd)


def test_read_rtl_inputs_raises_on_malformed_json(tmp_path):
    wd = write_rtl_inputs(tmp_path, {"files": ["src/a.v"]}, {"a": ANN})
    (wd / "rtl-files.json").write_text("{not json")
    with pytest.raises(RTLInputError):
        read_rtl_inputs(wd)
