# tests/unit/test_rtl_partition.py
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/rtl-design/scripts"))
from rtl._ledger import LedgerError  # noqa: E402
from rtl.partition import coverage_verdict, post_verdict  # noqa: E402

_PURE_MANIFEST = {
    "module": "top",
    "children": [
        {"name": "leaf", "rtl_modules": ["leaf_m"]},
        {"name": "topc", "rtl_modules": ["top"]},
    ],
}


def _coverage(tmp_path, top):
    """coverage_verdict is the rule specification decides at derive-ports;
    test_partition_purity_agreement.py locks the two together."""
    return coverage_verdict(tmp_path / "manifest.json", top)


def test_pre_phase_fails_bundled_top_manifest_only(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "top",
                "children": [
                    {"name": "leaf", "rtl_modules": ["leaf_m"]},
                    {"name": "topc", "rtl_modules": ["top", "wb_front"]},
                ],
            }
        )
    )
    status, reason = _coverage(tmp_path, "top")
    assert status == "fail" and "not pure" in reason


def test_pre_phase_fails_zero_coverage(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"module": "top", "children": [{"name": "leaf", "rtl_modules": ["leaf_m"]}]}
        )
    )
    status, reason = _coverage(tmp_path, "top")
    assert status == "fail" and "covered by 0 children" in reason


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


def _sidecars(tmp_path, files):
    (tmp_path / "rtl-files.json").write_text(json.dumps(files))
    (tmp_path / "constraint-annotations.json").write_text(
        json.dumps({name: _ANN for name in files})
    )


def test_post_verdict_raises_when_a_sidecar_is_absent(tmp_path):
    # No sidecars means no verdict is derivable at all. That is a broken run, not a routable
    # fail: LedgerError reaches finalize, which exits 2 BLOCKED without writing an envelope,
    # so nothing promotes over canonical.
    (tmp_path / "manifest.json").write_text(json.dumps(_PURE_MANIFEST))
    with pytest.raises(LedgerError):
        post_verdict(tmp_path / "manifest.json", tmp_path)


def test_post_verdict_raises_when_the_ledger_is_short_of_the_roster(tmp_path):
    # promote treats artifacts[] as the new canonical view and deletes what it omits, so passing
    # over a ledger short of the manifest roster would drop `leaf`'s RTL out of canonical.
    (tmp_path / "manifest.json").write_text(json.dumps(_PURE_MANIFEST))
    _sidecars(tmp_path, {"topc": {"files": ["top.v"]}})
    with pytest.raises(LedgerError, match="leaf"):
        post_verdict(tmp_path / "manifest.json", tmp_path)


def test_post_verdict_fail_still_enumerates_the_readable_ledger(tmp_path):
    # A fail envelope promotes exactly like a passing one, so a coverage fail must still report
    # what the sidecars hold: an empty artifacts[] over a live baseline is a wipe.
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "top",
                "children": [
                    {"name": "leaf", "rtl_modules": ["leaf_m"]},
                    {"name": "topc", "rtl_modules": ["top", "leaf_m"]},  # impure
                ],
            }
        )
    )
    _sidecars(tmp_path, {"leaf": {"files": ["leaf.v"]}, "topc": {"files": ["top.v"]}})
    verdict, rc = post_verdict(tmp_path / "manifest.json", tmp_path)
    assert rc == 1
    assert "not pure" in verdict["fail_reason"]
    assert {a["path"] for a in verdict["artifacts"]} == {
        "leaf.v",
        "top.v",
        "rtl-files.json",
        "constraint-annotations.json",
    }


def test_pre_phase_passes_pure_top_manifest_only(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "top",
                "children": [
                    {"name": "leaf", "rtl_modules": ["leaf_m"]},
                    {"name": "topc", "rtl_modules": ["top"]},
                ],
            }
        )
    )
    assert _coverage(tmp_path, "top") == ("pass", None)
