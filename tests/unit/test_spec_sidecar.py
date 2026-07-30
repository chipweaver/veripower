"""Sidecar reads validate on the way in — the file's own shape, reported by whoever read it.

Placement is the point being tested here: these defects are NOT cross-file, so they must not
wait for check-crossrefs. `read_sidecar` raising is what lets every verb (derive-ports,
derive-constraints, check-crossrefs) report the same defect the moment it needs the file.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/specification/scripts"))
from spec.sidecar import SidecarError, read_sidecar  # noqa: E402

_FEATURE = {"id": "F-00", "name": "f", "description": "d"}
_PORT = {
    "name": "din",
    "direction": "input",
    "width": 8,
    "clock_domain": "clk",
    "interface_group": "cfg",
    "role": "data",
}


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_missing_file_names_itself(tmp_path):
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "features.json")
    assert "features.json" in str(e.value) and "missing" in str(e.value)


def test_unparseable_file_names_itself(tmp_path):
    (tmp_path / "features.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "features.json")
    assert "unreadable" in str(e.value)


def test_clean_sidecar_returns_its_entries(tmp_path):
    _write(tmp_path, "features.json", [_FEATURE])
    assert read_sidecar(tmp_path, "features.json") == [_FEATURE]


def test_misspelled_key_names_itself(tmp_path):
    _write(tmp_path, "features.json", [{**_FEATURE, "happy_pat": "h"}])
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "features.json")
    assert "happy_pat" in str(e.value)


def test_missing_required_field_is_rejected(tmp_path):
    _write(
        tmp_path, "features.json", [{k: v for k, v in _FEATURE.items() if k != "id"}]
    )
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "features.json")
    assert "id" in str(e.value)


def test_narrative_fields_are_optional(tmp_path):
    # id/name/description carry the record; the rest describe the shape a feature record
    # usually takes. A required-non-empty box buys a filled box, not a real answer.
    _write(tmp_path, "features.json", [_FEATURE])
    assert read_sidecar(tmp_path, "features.json") == [_FEATURE]


def test_present_but_blank_is_rejected(tmp_path):
    # minLength 1 everywhere, optional fields included.
    _write(tmp_path, "features.json", [{**_FEATURE, "happy_path": ""}])
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "features.json")
    assert "happy_path" in str(e.value)


def test_empty_array_is_rejected_for_a_minitems_sidecar(tmp_path):
    _write(tmp_path, "features.json", [])
    with pytest.raises(SidecarError):
        read_sidecar(tmp_path, "features.json")


def test_error_names_every_violation_not_the_first(tmp_path):
    # Whoever is fixing the sidecar wants the whole list, not one round-trip per defect.
    _write(
        tmp_path,
        "features.json",
        [{**_FEATURE, "id": ""}, {k: v for k, v in _FEATURE.items() if k != "name"}],
    )
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "features.json")
    assert len(e.value.violations) == 2


def test_schema_override_for_a_subject_named_file(tmp_path):
    hint = {
        "check_id": "CHK-0",
        "source_feature": "F-00",
        "implementation_detail": "sum",
        "observable": "y",
        "reference_rule": "rm",
    }
    _write(tmp_path, "check-hints/c.json", [hint])
    got = read_sidecar(tmp_path, "check-hints/c.json", schema="check-hints.schema.json")
    assert got == [hint]


def test_hint_missing_required_field_is_rejected(tmp_path):
    lean = {"check_id": "CHK-0", "source_feature": "F-00", "observable": "y"}
    _write(tmp_path, "check-hints/c.json", [lean])
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "check-hints/c.json", schema="check-hints.schema.json")
    assert "reference_rule" in str(e.value)


def test_source_feature_alias_is_rejected_not_reinterpreted(tmp_path):
    aliased = {
        "check_id": "CHK-0",
        "SourceFeature": "F-00",
        "implementation_detail": "sum",
        "observable": "y",
        "reference_rule": "rm",
    }
    _write(tmp_path, "check-hints/c.json", [aliased])
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "check-hints/c.json", schema="check-hints.schema.json")
    assert "SourceFeature" in str(e.value) or "source_feature" in str(e.value)


# ---------- the one rule JSON Schema cannot carry ----------


def test_width_agrees_with_the_range_in_the_name(tmp_path):
    _write(tmp_path, "top-io.json", [{**_PORT, "name": "tok[4:0]", "width": 5}])
    assert read_sidecar(tmp_path, "top-io.json")[0]["width"] == 5


def test_width_disagreeing_with_the_name_is_rejected(tmp_path):
    _write(tmp_path, "top-io.json", [{**_PORT, "name": "tok[4:0]", "width": 8}])
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "top-io.json")
    assert "implies 5" in str(e.value)


def test_an_index_makes_no_width_claim(tmp_path):
    # tok[3] is a register-file element, not a bit range.
    _write(tmp_path, "top-io.json", [{**_PORT, "name": "tok[3]", "width": 32}])
    assert read_sidecar(tmp_path, "top-io.json")


def test_the_width_rule_applies_to_interconnects_too(tmp_path):
    _write(
        tmp_path,
        "interconnects.json",
        [
            {
                "wire": "score_S[7:0]",
                "producers": ["a"],
                "consumers": ["b"],
                "width": 32,
                "clock_domain": "clk",
            }
        ],
    )
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "interconnects.json")
    assert "implies 8" in str(e.value)


def test_a_wire_without_width_is_a_schema_violation(tmp_path):
    _write(
        tmp_path,
        "interconnects.json",
        [
            {
                "wire": "score_S",
                "producers": ["a"],
                "consumers": ["b"],
                "clock_domain": "clk",
            }
        ],
    )
    with pytest.raises(SidecarError) as e:
        read_sidecar(tmp_path, "interconnects.json")
    assert "width" in str(e.value)
