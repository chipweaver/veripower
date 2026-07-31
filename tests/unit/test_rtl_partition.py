# tests/unit/test_rtl_partition.py
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills/rtl-design/scripts"))
from rtl._ledger import LedgerError  # noqa: E402
from rtl.partition import exit_artifacts, ledger_artifacts  # noqa: E402

_MANIFEST = {
    "module": "top",
    "children": [
        {"name": "leaf", "rtl_modules": ["leaf_m"]},
        {"name": "topc", "rtl_modules": ["top"]},
    ],
}

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


def _sidecars(tmp_path, files, *, write_rtl=True):
    (tmp_path / "manifest.json").write_text(json.dumps(_MANIFEST))
    (tmp_path / "rtl-files.json").write_text(json.dumps(files))
    (tmp_path / "constraint-annotations.json").write_text(
        json.dumps({name: _ANN for name in files})
    )
    if write_rtl:
        for rec in files.values():
            for f in rec["files"]:
                (tmp_path / f).write_text("module m; endmodule\n")


def test_exit_artifacts_raises_when_a_sidecar_is_absent(tmp_path):
    # No sidecars means no artifacts[] is derivable at all. That is a broken run, not a routable
    # fail: LedgerError reaches finalize, which exits 2 BLOCKED without writing an envelope,
    # so nothing promotes over canonical.
    (tmp_path / "manifest.json").write_text(json.dumps(_MANIFEST))
    with pytest.raises(LedgerError):
        exit_artifacts(tmp_path / "manifest.json", tmp_path)


def test_exit_artifacts_raises_when_the_ledger_is_short_of_the_roster(tmp_path):
    # promote treats artifacts[] as the new canonical view and deletes what it omits, so passing
    # over a ledger short of the manifest roster would drop `leaf`'s RTL out of canonical.
    _sidecars(tmp_path, {"topc": {"files": ["top.v"]}})
    with pytest.raises(LedgerError, match="leaf"):
        exit_artifacts(tmp_path / "manifest.json", tmp_path)


def test_exit_artifacts_raises_on_a_file_no_child_wrote(tmp_path):
    # promote hardlinks every artifacts[] entry and raises on the first absent one — BEFORE the
    # outcome event is appended, so the round would hang with nothing in the log to repair from.
    # Named here instead, where re-dispatching the owning child still fixes it.
    _sidecars(
        tmp_path,
        {"leaf": {"files": ["leaf.v"]}, "topc": {"files": ["top.v"]}},
        write_rtl=False,
    )
    with pytest.raises(LedgerError, match="leaf.v"):
        exit_artifacts(tmp_path / "manifest.json", tmp_path)


def test_exit_artifacts_enumerates_the_files_and_both_sidecars(tmp_path):
    _sidecars(tmp_path, {"leaf": {"files": ["leaf.v"]}, "topc": {"files": ["top.v"]}})
    assert {
        a["path"] for a in exit_artifacts(tmp_path / "manifest.json", tmp_path)
    } == {
        "leaf.v",
        "top.v",
        "rtl-files.json",
        "constraint-annotations.json",
    }


def test_ledger_artifacts_drops_a_file_that_is_not_on_disk(tmp_path):
    # The caller-reported fail path enumerates best-effort: listing a file promote cannot find
    # would raise there instead, and the whole point of that path is that an envelope still gets
    # written over a workdir no verdict can be derived from.
    _sidecars(tmp_path, {"leaf": {"files": ["leaf.v"]}, "topc": {"files": ["top.v"]}})
    (tmp_path / "leaf.v").unlink()
    assert {a["path"] for a in ledger_artifacts(tmp_path)} == {
        "top.v",
        "rtl-files.json",
        "constraint-annotations.json",
    }
