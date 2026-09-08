"""Tests for simplan.hints.load_check_hints — the specification's authored hints."""

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
        "requirements": ["R-001"],
        "observable": "rdata",
        "reference_rule": "reg[addr]=wdata",
    }
]


def _spec(tmp_path, hints=None):
    (tmp_path / "check-hints.json").write_text(
        json.dumps(CHECK_HINTS if hints is None else hints)
    )
    return tmp_path


def test_hints_are_carried_verbatim(tmp_path):
    # What was authored, in authored order — no field selection, no tagging.
    assert load_check_hints(_spec(tmp_path)) == CHECK_HINTS


def test_pipes_in_a_rule_need_no_escaping(tmp_path):
    hints = [{**CHECK_HINTS[0], "reference_rule": "`sel | in | 3 | bank`"}]
    got = load_check_hints(_spec(tmp_path, hints))
    assert got[0]["reference_rule"] == "`sel | in | 3 | bank`"


def test_authored_order_is_kept(tmp_path):
    hints = [
        {**CHECK_HINTS[0], "check_id": "CHK-A"},
        {**CHECK_HINTS[0], "check_id": "CHK-B"},
    ]
    assert [h["check_id"] for h in load_check_hints(_spec(tmp_path, hints))] == [
        "CHK-A",
        "CHK-B",
    ]


def test_duplicate_check_id_raises(tmp_path):
    # check_id is the coverage matrix's key: a collision would collapse in a by-id map,
    # making one testpoint appear to cover both and leaving the second silently unverified.
    with pytest.raises(HintsError, match="duplicate check_id"):
        load_check_hints(_spec(tmp_path, CHECK_HINTS + CHECK_HINTS))


def test_missing_hints_file_raises(tmp_path):
    with pytest.raises(HintsError, match="check-hints.json"):
        load_check_hints(tmp_path)


def test_entry_without_check_id_raises(tmp_path):
    bad = [{k: v for k, v in CHECK_HINTS[0].items() if k != "check_id"}]
    with pytest.raises(HintsError, match="check_id"):
        load_check_hints(_spec(tmp_path, bad))
