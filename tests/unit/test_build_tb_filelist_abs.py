# tests/unit/test_build_tb_filelist_abs.py
"""Tests for skills/power-analysis/templates/scripts/build_tb_filelist_abs.py.

This stage compiles the same testbench the simulation stage did, from a different working
directory and against the gate netlist. So the rewrite has exactly two jobs: replace the RTL,
and make every remaining path resolve from here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "power-analysis" / "templates" / "scripts"))

import build_tb_filelist_abs as b  # noqa: E402


def _run(lines, tb="/sim"):
    acc: list[str] = []
    b.absolutize(lines, tb, acc)
    return acc


def test_the_rtl_list_is_the_one_thing_dropped():
    assert _run(["-f rtl_filelist.f", "tb/uvm/pkg/tb_pkg.sv"]) == [
        "/sim/tb/uvm/pkg/tb_pkg.sv"
    ]


def test_relative_paths_and_incdirs_are_anchored_at_the_tb_dir():
    assert _run(["+incdir+tb/uvm/seq", "tb/uvm/top/t_tb_top.sv"]) == [
        "+incdir+/sim/tb/uvm/seq",
        "/sim/tb/uvm/top/t_tb_top.sv",
    ]


def test_absolute_and_env_paths_pass_through():
    assert _run(["${UVM_HOME}/src/uvm_pkg.sv", "/opt/x.sv", "+incdir+/opt/inc"]) == [
        "${UVM_HOME}/src/uvm_pkg.sv",
        "/opt/x.sv",
        "+incdir+/opt/inc",
    ]


def test_a_pulled_in_list_is_inlined_not_referenced(tmp_path):
    """Its paths are relative to the simulation directory, which is not where this stage runs,
    so passing the reference through would leave VCS resolving them against the wrong root."""
    (tmp_path / "tb" / "uvm").mkdir(parents=True)
    (tmp_path / "tb" / "uvm" / "tb_sources.f").write_text(
        "// a comment\ntb/uvm/refmodel/m_ref.c\n"
    )
    assert _run(["-f tb/uvm/tb_sources.f"], tb=str(tmp_path)) == [
        "// a comment",
        f"{tmp_path}/tb/uvm/refmodel/m_ref.c",
    ]
