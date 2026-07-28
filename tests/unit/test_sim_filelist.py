# tests/unit/test_sim_filelist.py
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import _filelist  # noqa: E402

_RTL_ROOT = "/abs/injected/rtl-design"


def _run(tmp_path, rtl_files, rtl_root=_RTL_ROOT):
    dst = tmp_path / "rtl_filelist.f"
    _filelist.write_rtl_filelist(rtl_files, dst, rtl_root)
    return dst.read_text()


def test_paths_anchored_at_the_absolute_rtl_root(tmp_path):
    out = _run(tmp_path, {"c": {"files": ["rtl/core.v", "sub/mod.sv"]}})
    assert f"{_RTL_ROOT}/rtl/core.v" in out
    assert f"{_RTL_ROOT}/sub/mod.sv" in out
    assert "../" not in out  # absolute rtl root -> no relpath climb


def test_absolute_and_env_paths_pass_through(tmp_path):
    out = _run(tmp_path, {"c": {"files": ["/abs/path.v", "$ENV/x.sv"]}})
    assert "/abs/path.v" in out
    assert "$ENV/x.sv" in out
    assert f"{_RTL_ROOT}//abs" not in out


def test_incdirs_become_the_only_incdir_lines(tmp_path):
    # `+incdir+` is written here and nowhere else: upstream carries incdirs as a field.
    out = _run(tmp_path, {"c": {"files": ["top.v"], "incdirs": ["sub/inc"]}})
    assert f"+incdir+{_RTL_ROOT}/sub/inc" in out
    assert f"{_RTL_ROOT}/top.v" in out
    # the include dir never lands in the source list as a bare path, which is what the
    # old text round-trip could do when a reader's skip set missed the prefix
    assert f"{_RTL_ROOT}/sub/inc" not in out.splitlines()


def test_children_in_name_order_files_in_declared_order(tmp_path):
    out = _run(
        tmp_path,
        {"z": {"files": ["z1.v", "z0.v"]}, "a": {"files": ["a.v"]}},
    )
    lines = [ln for ln in out.splitlines() if ln and not ln.startswith("//")]
    assert lines == [
        f"{_RTL_ROOT}/a.v",
        f"{_RTL_ROOT}/z1.v",
        f"{_RTL_ROOT}/z0.v",
    ]


def test_duplicate_file_across_children_emitted_once(tmp_path):
    out = _run(tmp_path, {"a": {"files": ["shared.vh"]}, "b": {"files": ["shared.vh"]}})
    assert out.count(f"{_RTL_ROOT}/shared.vh") == 1


def test_generated_header_marks_it_non_hand_editable(tmp_path):
    out = _run(tmp_path, {"c": {"files": ["top.v"]}})
    assert out.splitlines()[0].startswith("//")
    assert "rtl-files.json" in out.splitlines()[0]


def test_load_rtl_files_reads_the_injected_root(tmp_path):
    doc = {"c": {"files": ["top.v"]}}
    (tmp_path / "rtl-files.json").write_text(json.dumps(doc))
    assert _filelist.load_rtl_files(tmp_path) == doc
