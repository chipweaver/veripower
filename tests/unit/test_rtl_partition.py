# tests/unit/test_rtl_partition.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"


def _run_pre(tmp_path, top):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-partition",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--top",
            top,
        ],
        capture_output=True,
        text=True,
    )


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
    r = _run_pre(tmp_path, "top")
    assert r.returncode == 1
    assert "not pure" in json.loads(r.stdout)["fail_reason"]


def test_pre_phase_fails_zero_coverage(tmp_path):
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
