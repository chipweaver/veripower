"""bootstrap_synthesis.sh expands +incdir+ entries onto search_path in rtl_load.tcl."""

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _mirror_and_run(tmp_path, filelist_body):
    """Copy skills/synthesis into tmp, stage an RTL filelist, run bootstrap. Return (proc, rtl_load_text)."""
    skill_dst = tmp_path / "skills" / "synthesis"
    shutil.copytree(REPO_ROOT / "skills" / "synthesis", skill_dst)
    rtl = tmp_path / "asic" / "M" / "Design" / "rtl-design"
    rtl.mkdir(parents=True)
    (rtl / "filelist.txt").write_text(filelist_body)
    workdir = tmp_path / "asic" / "M" / "Design" / "synthesis" / "runs" / "1"
    proc = subprocess.run(
        [
            "bash",
            str(skill_dst / "scripts" / "bootstrap_synthesis.sh"),
            "--module",
            "M",
            "--workdir",
            str(workdir),
            "--top",
            "top",
        ],
        capture_output=True,
        text=True,
    )
    gen = workdir / "scripts" / "rtl_load.tcl"
    return proc, (gen.read_text() if gen.exists() else "")


def test_incdir_becomes_search_path_entry(tmp_path):
    proc, gen = _mirror_and_run(tmp_path, "+incdir+sub/inc\ntop.v\n")
    assert proc.returncode == 0, proc.stderr
    # +incdir+ expanded onto search_path (RTL_REL_DIR-relative), not dropped.
    assert "set_app_var search_path" in gen
    assert "sub/inc" in gen
    # the directive itself is never emitted verbatim
    assert "+incdir+" not in gen
    # the real RTL file is still analyzed
    assert "analyze -format sverilog -define SYNTHESIS" in gen
    assert "top.v" in gen


def test_define_and_dashf_still_skipped(tmp_path):
    proc, gen = _mirror_and_run(tmp_path, "+define+FOO=1\n-f other.f\ntop.v\n")
    assert proc.returncode == 0, proc.stderr
    assert "FOO" not in gen  # +define+ not expanded
    assert "other.f" not in gen  # -f not expanded
    assert "top.v" in gen  # real file analyzed
