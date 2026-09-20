"""Stage results appear only after a complete JSON document has been written."""

import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("stage", "package", "arguments"),
    [
        ("specification", "spec", {}),
        ("simulation-plan", "simplan", {"spec_workdir": None}),
        ("rtl-design", "rtl", {}),
        ("lint-cdc", "lintcdc", {"rows": [], "declared": []}),
        ("simulation", "sim", {"phase": "fail"}),
        ("synthesis", "synthesis", {"rows": [], "declared": []}),
        ("timing-analysis", "timing", {"rows": [], "declared": []}),
        ("power-analysis", "power", {"plan": None, "rows": [], "declared": []}),
        ("simulation-triage", "simtriage", {}),
    ],
)
def test_result_json_written_atomically(
    tmp_path, monkeypatch, stage, package, arguments
):
    monkeypatch.syspath_prepend(str(ROOT / "skills" / stage / "scripts"))
    result_module = importlib.import_module(f"{package}.result")
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps({"previous": True}))
    if stage == "specification":
        (tmp_path / "manifest.json").write_text(json.dumps({"module": "dut"}))
    arguments = {**arguments, "fail_reason": "The assigned work is incomplete"}
    if stage == "simulation-triage":
        analysis_path = tmp_path / "diagnosis.json"
        analysis_path.write_text(
            json.dumps({"findings": [], "reason": "More evidence is needed"})
        )
        arguments = {"json_file": analysis_path, "json_stdin": False}

    replace = Path.replace
    published = []

    def _replace(source, target):
        assert Path(target) == result_path
        assert source != result_path and source.parent == result_path.parent
        assert not result_path.exists()
        document = json.loads(source.read_text())
        assert document["stage"] == stage
        assert document["status"] == (
            "pass" if stage == "simulation-triage" else "fail"
        )
        published.append(document)
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", _replace)
    assert result_module.finalize(tmp_path, **arguments) == 0
    assert published == [json.loads(result_path.read_text())]
