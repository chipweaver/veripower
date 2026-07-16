# tests/unit/test_sim_filelist.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import _filelist  # noqa: E402


def _run(tmp_path, text, rtl_rel="/abs/injected/rtl-design"):
    src = tmp_path / "filelist.txt"
    dst = tmp_path / "rtl_filelist.f"
    src.write_text(text)
    _filelist.rewrite_rtl_filelist(src, dst, rtl_rel)
    return dst.read_text()


def test_filelist_rebases_relative(tmp_path):
    out = _run(tmp_path, "rtl/core.v\nsub/mod.sv\n")
    assert "/abs/injected/rtl-design/rtl/core.v" in out
    assert "/abs/injected/rtl-design/sub/mod.sv" in out
    assert "../" not in out  # absolute rtl root -> no relpath climb


def test_filelist_passes_absolute(tmp_path):
    out = _run(tmp_path, "/abs/path.v\n$ENV/x.sv\n")
    assert "/abs/path.v" in out
    assert "$ENV/x.sv" in out
    assert "/abs/injected/rtl-design//abs" not in out


def test_filelist_incdir_rebase(tmp_path):
    out = _run(tmp_path, "+incdir+include\n+incdir+/abs/inc\n")
    assert "+incdir+/abs/injected/rtl-design/include" in out
    assert "+incdir+/abs/inc" in out


def test_filelist_dashf_rebase(tmp_path):
    out = _run(tmp_path, "-f sub.f\n-f /abs/sub.f\n")
    assert "-f /abs/injected/rtl-design/sub.f" in out
    assert "-f /abs/sub.f" in out


def test_filelist_other_directives_passthrough(tmp_path):
    out = _run(tmp_path, "+define+FOO\n-define BAR\n")
    assert "+define+FOO" in out
    assert "-define BAR" in out


def test_filelist_preserves_comments_blanks(tmp_path):
    out = _run(tmp_path, "# header comment\n\nrtl/a.v\n")
    assert "# header comment" in out
    assert "/abs/injected/rtl-design/rtl/a.v" in out
