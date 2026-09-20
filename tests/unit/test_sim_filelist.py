# tests/unit/test_sim_filelist.py
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import rtl_sources  # noqa: E402

RTL_ROOT = "/abs/injected/rtl-design"


def run(tmp_path, rtl_files, rtl_root=RTL_ROOT):
    dst = tmp_path / "rtl_filelist.f"
    rtl_sources.write_rtl_filelist(rtl_files, dst, rtl_root)
    return dst.read_text()


def test_paths_anchored_at_the_absolute_rtl_root(tmp_path):
    out = run(tmp_path, {"files": ["rtl/core.v", "sub/mod.sv"]})
    assert f"{RTL_ROOT}/rtl/core.v" in out
    assert f"{RTL_ROOT}/sub/mod.sv" in out
    assert "../" not in out  # absolute rtl root -> no relpath climb


def test_absolute_and_env_paths_pass_through(tmp_path):
    out = run(tmp_path, {"files": ["/abs/path.v", "$ENV/x.sv"]})
    assert "/abs/path.v" in out
    assert "$ENV/x.sv" in out
    assert f"{RTL_ROOT}//abs" not in out


def test_incdirs_become_the_only_incdir_lines(tmp_path):
    # `+incdir+` is written here and nowhere else: upstream carries incdirs as a field.
    out = run(tmp_path, {"files": ["top.v"], "incdirs": ["sub/inc"]})
    assert f"+incdir+{RTL_ROOT}/sub/inc" in out
    assert f"{RTL_ROOT}/top.v" in out
    # the include dir never lands in the source list as a bare path, which is what the
    # old text round-trip could do when a reader's skip set missed the prefix
    assert f"{RTL_ROOT}/sub/inc" not in out.splitlines()


def test_global_dependency_order_is_preserved(tmp_path):
    out = run(
        tmp_path,
        {"files": ["z1.v", "z0.v"] + ["a.v"]},
    )
    lines = [ln for ln in out.splitlines() if ln and not ln.startswith("//")]
    assert lines == [
        f"{RTL_ROOT}/z1.v",
        f"{RTL_ROOT}/z0.v",
        f"{RTL_ROOT}/a.v",
    ]


def test_sim_only_sources_follow_the_files_that_import_them(tmp_path):
    """The C behind a DPI import the RTL declares reaches this filelist and no other: lint-cdc
    and synthesis build theirs from files[] alone, and a C source handed to either aborts the
    run before a rule is checked."""
    out = run(
        tmp_path,
        {"files": ["src/Sram.v"], "sim_only": ["src/dpi/sram_backdoor.cc"]},
    )
    body = [ln for ln in out.splitlines() if not ln.startswith("//")]
    assert body == [
        f"{RTL_ROOT}/src/Sram.v",
        f"{RTL_ROOT}/src/dpi/sram_backdoor.cc",
    ]


def test_generated_header_marks_it_non_hand_editable(tmp_path):
    out = run(tmp_path, {"files": ["top.v"]})
    assert out.splitlines()[0].startswith("//")
    assert "rtl-files.json" in out.splitlines()[0]


def test_load_rtl_files_reads_the_injected_root(tmp_path):
    doc = {"files": ["top.v"]}
    (tmp_path / "rtl-files.json").write_text(json.dumps(doc))
    assert rtl_sources.load_rtl_files(tmp_path) == doc
