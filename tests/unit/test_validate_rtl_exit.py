# tests/unit/test_validate_rtl_exit.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/rtl-design/scripts/validate_rtl_exit.py"
_ANN = {"sgdc": {}, "sdc": {}}


def _setup(tmp_path, children, fresh, ledger):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "top", "children": children})
    )
    (tmp_path / "fresh.json").write_text(json.dumps(fresh))
    (tmp_path / ".child_reports.json").write_text(json.dumps(ledger))


def _run(tmp_path, top, check=False):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--top",
            top,
            "--fresh",
            str(tmp_path / "fresh.json"),
            "--ledger",
            str(tmp_path / ".child_reports.json"),
        ],
        capture_output=True,
        text=True,
        check=check,
    )


def test_pass_exactly_one_top_child(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {"leaf": {"status": "done"}, "topc": {"status": "done"}},
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 0
    v = json.loads(r.stdout)
    assert v["status"] == "pass"
    # Envelope shape: artifacts is a list of {"path": ...} objects (NOT flat strings).
    # Asserting on the object shape is what makes this test catch M1 instead of masking it.
    assert all(isinstance(a, dict) and "path" in a for a in v["artifacts"])
    paths = {a["path"] for a in v["artifacts"]}
    assert ".child_reports.json" in paths
    assert "filelist.txt" in paths and "README.md" in paths
    assert "leaf.sv" in paths and "top.sv" in paths


def test_fail_zero_top_children(tmp_path):
    _setup(
        tmp_path,
        [{"name": "leaf", "rtl_modules": ["leaf_m"]}],
        {"leaf": {"status": "done"}},
        {"leaf": {"files": ["leaf.sv"], "annotations": _ANN}},
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "covered by 0 children" in json.loads(r.stdout)["fail_reason"]


def test_fail_two_top_children(tmp_path):
    _setup(
        tmp_path,
        [{"name": "a", "rtl_modules": ["top"]}, {"name": "b", "rtl_modules": ["top"]}],
        {"a": {"status": "done"}, "b": {"status": "done"}},
        {
            "a": {"files": ["a.sv"], "annotations": _ANN},
            "b": {"files": ["b.sv"], "annotations": _ANN},
        },
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "covered by 2 children" in json.loads(r.stdout)["fail_reason"]


def test_fail_when_child_blocked(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"status": "blocked", "reason": "iface incomplete"},
            "topc": {"status": "done"},
        },
        {"topc": {"files": ["top.sv"], "annotations": _ANN}},
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "blocked" in json.loads(r.stdout)["fail_reason"]


def test_fail_top_child_not_pure(tmp_path):
    """L2 purity: a top-integration child bundling a logic module fails (post phase)."""
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top", "wb_front"]},
        ],
        {"leaf": {"status": "done"}, "topc": {"status": "done"}},
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
    )
    r = _run(tmp_path, "top")
    assert r.returncode == 1
    assert "not pure" in json.loads(r.stdout)["fail_reason"]


def _run_pre(tmp_path, top):
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--top",
            top,
            "--phase",
            "pre",
        ],
        capture_output=True,
        text=True,
    )


def test_pre_phase_fails_bundled_top_manifest_only(tmp_path):
    """L2 pre-dispatch: --phase pre checks coverage+purity from manifest+top only (no reports)."""
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
    r = _run_pre(tmp_path, "top")
    assert r.returncode == 1
    assert "not pure" in json.loads(r.stdout)["fail_reason"]


def test_pre_phase_fails_zero_coverage(tmp_path):
    """--phase pre with no covering child fails (coverage check, manifest-only)."""
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"module": "top", "children": [{"name": "leaf", "rtl_modules": ["leaf_m"]}]}
        )
    )
    r = _run_pre(tmp_path, "top")
    assert r.returncode == 1
    assert "covered by 0 children" in json.loads(r.stdout)["fail_reason"]


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
    r = _run_pre(tmp_path, "top")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "pass"
    assert json.loads(r.stdout)["artifacts"] == []
