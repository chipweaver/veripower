# tests/unit/test_build_filelist.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/rtl-design/scripts/build_filelist.py"
_ANN = {"sgdc": {}, "sdc": {}}


def _run(ledger, out, check=True):
    return subprocess.run(
        ["python3", str(SCRIPT), "--ledger", str(ledger), "--out", str(out)],
        capture_output=True,
        text=True,
        check=check,
    )


def _ledger(tmp_path, obj):
    p = tmp_path / ".child_reports.json"
    p.write_text(json.dumps(obj))
    return p


def test_aggregates_files_and_incdirs(tmp_path):
    led = _ledger(
        tmp_path,
        {
            "a": {"files": ["a.sv"], "incdirs": ["inc"], "annotations": _ANN},
            "b": {"files": ["b.sv"], "annotations": _ANN},
        },
    )
    out = tmp_path / "filelist.txt"
    _run(led, out)
    text = out.read_text()
    assert "+incdir+inc" in text
    assert "a.sv" in text and "b.sv" in text
    assert "//" not in text  # SpyGlass: '#' comments only


def test_dedups_shared_file(tmp_path):
    led = _ledger(
        tmp_path,
        {
            "a": {"files": ["pkg.sv", "a.sv"], "annotations": _ANN},
            "b": {"files": ["pkg.sv", "b.sv"], "annotations": _ANN},
        },
    )
    out = tmp_path / "filelist.txt"
    _run(led, out)
    assert out.read_text().count("pkg.sv") == 1


def test_fail_loud_on_malformed_ledger_F8(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"a": {"files": ["a.sv"]}}')  # missing annotations
    out = tmp_path / "filelist.txt"
    r = _run(bad, out, check=False)
    assert r.returncode == 1
    assert not out.exists()  # no degraded output
