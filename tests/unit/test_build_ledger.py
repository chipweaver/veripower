# tests/unit/test_build_ledger.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/rtl-design/scripts/build_ledger.py"
_ANN = {"sgdc": {}, "sdc": {}}


def _write(p, obj):
    p.write_text(json.dumps(obj), encoding="utf-8")


def _run(args, check=True):
    return subprocess.run(
        ["python3", str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        check=check,
    )


def _manifest(*names):
    return {
        "module": "top",
        "children": [{"name": n, "rtl_modules": []} for n in names],
    }


def test_first_run_all_children(tmp_path):
    fresh = {
        "a": {"status": "done", "files": ["a.sv"], "annotations": _ANN},
        "b": {"status": "done", "files": ["b.sv"], "annotations": _ANN},
    }
    _write(tmp_path / "fresh.json", fresh)
    _write(tmp_path / "manifest.json", _manifest("a", "b"))
    out = tmp_path / ".child_reports.json"
    _run(
        [
            "--fresh",
            tmp_path / "fresh.json",
            "--manifest",
            tmp_path / "manifest.json",
            "--out",
            out,
        ]
    )
    ledger = json.loads(out.read_text())
    assert set(ledger) == {"a", "b"}
    assert "status" not in ledger["a"]  # status stripped from ledger


def test_subset_rework_overlays_seeded(tmp_path):
    seeded = {
        "a": {"files": ["a.sv"], "annotations": _ANN},
        "b": {"files": ["b_old.sv"], "annotations": _ANN},
    }
    _write(tmp_path / ".child_reports.json", seeded)
    fresh = {"b": {"status": "done", "files": ["b_new.sv"], "annotations": _ANN}}
    _write(tmp_path / "fresh.json", fresh)
    _write(tmp_path / "manifest.json", _manifest("a", "b"))
    out = tmp_path / ".child_reports.json"
    _run(
        [
            "--fresh",
            tmp_path / "fresh.json",
            "--manifest",
            tmp_path / "manifest.json",
            "--out",
            out,
            "--seeded",
            tmp_path / ".child_reports.json",
        ]
    )
    ledger = json.loads(out.read_text())
    assert ledger["b"]["files"] == ["b_new.sv"]  # re-dispatched child updated
    assert ledger["a"]["files"] == ["a.sv"]  # unchanged carried forward


def test_manifest_shrink_evicts_removed_child_F2(tmp_path):
    seeded = {
        "a": {"files": ["a.sv"], "annotations": _ANN},
        "gone": {"files": ["gone.sv"], "annotations": _ANN},
    }
    _write(tmp_path / ".child_reports.json", seeded)
    _write(tmp_path / "fresh.json", {})
    _write(tmp_path / "manifest.json", _manifest("a"))  # 'gone' dropped
    out = tmp_path / ".child_reports.json"
    _run(
        [
            "--fresh",
            tmp_path / "fresh.json",
            "--manifest",
            tmp_path / "manifest.json",
            "--out",
            out,
            "--seeded",
            tmp_path / ".child_reports.json",
        ]
    )
    ledger = json.loads(out.read_text())
    assert "gone" not in ledger


def test_blocked_child_excluded(tmp_path):
    fresh = {
        "a": {"status": "done", "files": ["a.sv"], "annotations": _ANN},
        "b": {"status": "blocked", "reason": "iface incomplete"},
    }
    _write(tmp_path / "fresh.json", fresh)
    _write(tmp_path / "manifest.json", _manifest("a", "b"))
    out = tmp_path / ".child_reports.json"
    _run(
        [
            "--fresh",
            tmp_path / "fresh.json",
            "--manifest",
            tmp_path / "manifest.json",
            "--out",
            out,
        ]
    )
    ledger = json.loads(out.read_text())
    assert set(ledger) == {"a"}  # blocked child has no ledger entry


def test_done_child_missing_required_field_fails_loud_C1_06(tmp_path):
    # A done child MUST return 'files' + 'annotations' (child-task-contract). A missing
    # 'files' is a contract violation that would silently drop that child's RTL from
    # filelist.txt (Iron Rule #1) if defaulted — build_ledger must fail loudly instead.
    fresh = {"a": {"status": "done", "annotations": _ANN}}  # no 'files'
    _write(tmp_path / "fresh.json", fresh)
    _write(tmp_path / "manifest.json", _manifest("a"))
    out = tmp_path / ".child_reports.json"
    r = _run(
        [
            "--fresh",
            tmp_path / "fresh.json",
            "--manifest",
            tmp_path / "manifest.json",
            "--out",
            out,
        ],
        check=False,
    )
    assert r.returncode == 1
    assert "missing required 'files'" in r.stderr
    assert not out.exists()  # no degraded ledger written
