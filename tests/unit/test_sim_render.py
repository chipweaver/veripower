# tests/unit/test_sim_render.py
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "simulation" / "scripts"))
from sim import rendering  # noqa: E402


def test_render_rejects_unknown_placeholder(tmp_path):
    (tmp_path / "sample.sv").write_text("hello {{MISSING}}")
    with pytest.raises(KeyError):
        rendering.render_template_file(tmp_path, "sample.sv", {"OTHER": "x"})


def test_render_preserves_sv_braces(tmp_path):
    (tmp_path / "sample.sv").write_text("assign x = {{A}}; concat = {8'h0F, y};")
    # SystemVerilog single-braces must survive untouched; only {{KEY}} is a placeholder.
    out = rendering.render_template_file(tmp_path, "sample.sv", {"A": "1'b0"})
    assert out == "assign x = 1'b0; concat = {8'h0F, y};"


def test_signal_decl_width():
    out = rendering.signal_declarations(
        [
            {"name": "a", "width": 8, "direction": "input"},
            {"name": "b", "width": 1, "direction": "output"},
        ]
    )
    assert "logic [7:0] a;" in out
    assert "logic        b;" in out
