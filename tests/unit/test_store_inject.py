import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import store  # noqa: E402


def test_inject_upstream_keys_are_producer_stage_roots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Design" / "synthesis" / "runs" / "1"
    wd.mkdir(parents=True)
    store.inject_inputs("m", "synthesis", wd)
    table = json.loads((wd / "inputs.json").read_text())
    base = str((tmp_path / "asic" / "m").resolve())
    assert table["rtl"] == base + "/Design/rtl-design"
    assert table["sdc"] == base + "/Design/specification"
    assert table["ppa"] == base + "/Design/specification"


def test_inject_pipeline_input_resolves_to_module_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Design" / "specification" / "runs" / "1"
    wd.mkdir(parents=True)
    store.inject_inputs("m", "specification", wd)
    table = json.loads((wd / "inputs.json").read_text())
    assert table["brainstorm"] == str((tmp_path / "asic" / "m").resolve())


def test_inject_sim_run_key_and_guard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Verification" / "simulation-triage" / "runs" / "1"
    wd.mkdir(parents=True)
    store.inject_inputs("m", "simulation-triage", wd, params={"sim_run": "3"})
    table = json.loads((wd / "inputs.json").read_text())
    sim_root = str((tmp_path / "asic" / "m" / "Verification" / "simulation").resolve())
    assert table["sim_run"] == sim_root + "/runs/3"


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1/../2", "../9"])
def test_resolve_sim_run_rejects(tmp_path, bad):
    with pytest.raises(ValueError):
        store._resolve_sim_run(Path(tmp_path) / "asic" / "m", bad)
