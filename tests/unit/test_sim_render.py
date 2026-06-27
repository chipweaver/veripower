# tests/unit/test_sim_render.py
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import _render  # noqa: E402


def test_render_strict_raises_unknown_key():
    with pytest.raises(KeyError):
        _render._render_strict("hello {{MISSING}}", {"OTHER": "x"})


def test_render_strict_leaves_sv_braces():
    # SystemVerilog single-braces must survive untouched; only {{KEY}} is a placeholder.
    out = _render._render_strict(
        "assign x = {{A}}; concat = {8'h0F, y};", {"A": "1'b0"}
    )
    assert out == "assign x = 1'b0; concat = {8'h0F, y};"


def test_signal_decl_width():
    out = _render._signal_declarations(
        [{"name": "a", "width": 8}, {"name": "b", "width": 1}]
    )
    assert "logic [7:0] a;" in out
    assert "logic        b;" in out


def test_field_decl_types():
    out = _render._field_declarations(
        [
            {"name": "cnt", "type": "int", "rand": True},
            {"name": "data", "width": 16, "rand": True},
            {"name": "flag", "width": 1},
        ]
    )
    assert "rand int cnt;" in out
    assert "rand logic [15:0] data;" in out
    assert "logic        flag;" in out


def test_field_macros():
    out = _render._field_macros([{"name": "a"}, {"name": "b"}])
    assert "`uvm_field_int(a, UVM_ALL_ON)" in out
    assert "`uvm_field_int(b, UVM_ALL_ON)" in out


def test_render_missing_template_exits(tmp_path):
    with pytest.raises(SystemExit):
        _render._render_template_file(tmp_path, "nope.sv", {})
