"""Sidecar reads validate on the way in — the file's own shape, reported by whoever read it.

Placement is the point being tested here: these defects are NOT cross-file, so they must not
wait for check-crossrefs. `read_sidecar` raising is what lets every verb (check-ledger,
derive-ports, derive-constraints, check-crossrefs) report the same defect the moment it needs
the file.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/specification/scripts"))
from spec.sidecar import SidecarError, read_sidecar  # noqa: E402

_ROW = {
    "id": "R-001",
    "verbatim": "done pulses one cycle after start",
    "judge": "simulation",
}
_PORT = {
    "name": "din",
    "direction": "input",
    "width": 8,
    "clock_domain": "clk",
    "interface_group": "cfg",
    "role": "data",
}
_HINT = {
    "check_id": "CHK-0",
    "requirements": ["R-001"],
    "observable": "y",
    "reference_rule": "rm",
}


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def _bad(tmp_path, doc, name="requirements.json"):
    _write(tmp_path, name, doc)
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, name)
    return str(e.value), e.value.violations


def test_missing_file_names_itself(tmp_path):
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "requirements.json")
    assert "requirements.json" in str(e.value) and "missing" in str(e.value)


def test_unparseable_file_names_itself(tmp_path):
    (tmp_path / "requirements.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "requirements.json")
    assert "unreadable" in str(e.value)


def test_clean_ledger_returns_its_rows(tmp_path):
    _write(tmp_path, "requirements.json", [_ROW])
    assert read_sidecar(tmp_path, "requirements.json") == [_ROW]


def test_misspelled_key_names_itself(tmp_path):
    msg, _ = _bad(tmp_path, [{**_ROW, "verbatm": "x"}])
    assert "verbatm" in msg


def test_missing_required_field_is_rejected(tmp_path):
    msg, _ = _bad(tmp_path, [{k: v for k, v in _ROW.items() if k != "verbatim"}])
    assert "verbatim" in msg


def test_present_but_blank_is_rejected(tmp_path):
    msg, _ = _bad(tmp_path, [{**_ROW, "note": ""}])
    assert "note" in msg


def test_empty_ledger_is_rejected(tmp_path):
    _bad(tmp_path, [])


def test_unknown_judge_is_rejected(tmp_path):
    msg, _ = _bad(tmp_path, [{**_ROW, "judge": "verification"}])
    assert "verification" in msg


def test_error_names_every_violation_not_the_first(tmp_path):
    # Whoever is fixing the sidecar wants the whole list, not one round-trip per defect.
    _, violations = _bad(
        tmp_path,
        [{**_ROW, "id": ""}, {k: v for k, v in _ROW.items() if k != "judge"}],
    )
    assert len(violations) == 2


# ---------- the rules JSON Schema cannot carry ----------


def test_duplicate_id_is_rejected(tmp_path):
    msg, _ = _bad(tmp_path, [_ROW, {**_ROW, "verbatim": "again"}])
    assert "already used" in msg


def test_unassignable_needs_a_note(tmp_path):
    msg, _ = _bad(tmp_path, [{**_ROW, "judge": "unassignable"}])
    assert "note" in msg
    _write(
        tmp_path,
        "requirements.json",
        [{**_ROW, "judge": "unassignable", "note": "no measurand named"}],
    )
    assert read_sidecar(tmp_path, "requirements.json")[0]["judge"] == "unassignable"


def test_a_matching_target_is_accepted(tmp_path):
    row = {
        **_ROW,
        "judge": "synthesis",
        "target": {"dim": "area_um2", "op": "<=", "value": 7e5},
    }
    _write(tmp_path, "requirements.json", [row])
    assert read_sidecar(tmp_path, "requirements.json") == [row]


def test_scenario_only_qualifies_a_power_bound(tmp_path):
    t = {"dim": "coverage_line", "op": ">", "value": 90, "scenario": "idle"}
    msg, _ = _bad(tmp_path, [{**_ROW, "target": t}])
    assert "scenario" in msg


def test_non_finite_target_value_is_rejected(tmp_path):
    # json.loads accepts the NaN token and `type: number` admits it; a NaN bound makes every
    # comparison false and disarms the gate that reads it.
    (tmp_path / "requirements.json").write_text(
        '[{"id":"R-001","verbatim":"v","judge":"synthesis",'
        '"target":{"dim":"area_um2","op":"<=","value":NaN}}]'
    )
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "requirements.json")
    assert "finite" in str(e.value)


def test_hints_validate_against_their_own_schema(tmp_path):
    _write(tmp_path, "check-hints.json", [_HINT])
    assert read_sidecar(tmp_path, "check-hints.json") == [_HINT]


def test_hint_missing_required_field_is_rejected(tmp_path):
    lean = {k: v for k, v in _HINT.items() if k != "reference_rule"}
    msg, _ = _bad(tmp_path, [lean], name="check-hints.json")
    assert "reference_rule" in msg


def test_hint_naming_no_row_is_rejected(tmp_path):
    msg, _ = _bad(
        tmp_path,
        [{**_HINT, "requirements": []}],
        name="check-hints.json",
    )
    assert "requirements" in msg


def test_hint_alias_field_is_rejected_not_reinterpreted(tmp_path):
    aliased = {
        **{k: v for k, v in _HINT.items() if k != "requirements"},
        "rows": ["R-001"],
    }
    msg, _ = _bad(tmp_path, [aliased], name="check-hints.json")
    assert "rows" in msg or "requirements" in msg


def test_a_top_io_name_is_the_base_identifier(tmp_path):
    _write(tmp_path, "top-io.json", [{**_PORT, "name": "tok", "width": 5}])
    assert read_sidecar(tmp_path, "top-io.json")[0]["name"] == "tok"


def test_a_bit_range_in_a_top_io_name_is_rejected(tmp_path):
    # It reaches get_ports verbatim, where DC and PrimeTime match zero ports for it —
    # the port silently loses its IO constraint. Agreeing with `width` does not save it.
    msg, _ = _bad(
        tmp_path, [{**_PORT, "name": "tok[4:0]", "width": 5}], name="top-io.json"
    )
    assert "bit range" in msg and "tok[4:0]" in msg


def test_a_parameterized_range_in_a_top_io_name_is_rejected(tmp_path):
    msg, _ = _bad(
        tmp_path, [{**_PORT, "name": "dataIn[DATA_WIDTH-1:0]"}], name="top-io.json"
    )
    assert "bit range" in msg


def test_a_bit_select_in_a_top_io_name_is_rejected(tmp_path):
    msg, _ = _bad(
        tmp_path, [{**_PORT, "name": "tok[3]", "width": 32}], name="top-io.json"
    )
    assert "bit range" in msg
