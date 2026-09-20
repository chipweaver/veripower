"""Implementation changes and assessment-only notes have different consumers."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework/scripts"))
import kernel  # noqa: E402


@pytest.mark.parametrize("consumer", ["timing-analysis", "power-analysis"])
@pytest.mark.parametrize(
    "support",
    ["constraints/operating.tcl", "macros/model.v", "tables/load.data", "top_syn.sdf"],
)
def test_referenced_implementation_files_change_recorded_inputs(
    tmp_path, consumer, support
):
    syn = tmp_path / "Design/synthesis"
    out = syn / "out"
    out.mkdir(parents=True)
    (out / "top_syn.v").write_text("module top; endmodule")
    (out / "top_syn.sdc").write_text("source constraints/operating.tcl")
    helper = out / support
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("original")
    before = kernel.resolve_inputs(str(tmp_path), consumer)
    helper.write_text("changed")
    assert kernel.resolve_inputs(str(tmp_path), consumer) != before

    changed = kernel.resolve_inputs(str(tmp_path), consumer)
    (syn / "evidence").mkdir()
    (syn / "evidence/reassessment.md").write_text("New budget, same implementation")
    (syn / "result.json").write_text('{"status":"fail"}')
    assert kernel.resolve_inputs(str(tmp_path), consumer) == changed
