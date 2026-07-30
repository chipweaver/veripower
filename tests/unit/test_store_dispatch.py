import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "framework" / "scripts"))
import store  # noqa: E402


def _read(wd):
    return json.loads((wd / "dispatch.json").read_text())


def test_inject_upstream_keys_are_producer_stage_roots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Design" / "synthesis" / "runs" / "1"
    wd.mkdir(parents=True)
    store.write_dispatch("m", "synthesis", wd)
    table = _read(wd)["inputs"]
    base = str((tmp_path / "asic" / "m").resolve())
    assert table["rtl"] == base + "/Design/rtl-design"
    assert table["sdc"] == base + "/Design/specification"
    assert table["ppa"] == base + "/Design/specification"


def test_inject_pipeline_input_resolves_to_module_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Design" / "specification" / "runs" / "1"
    wd.mkdir(parents=True)
    store.write_dispatch("m", "specification", wd)
    assert _read(wd)["inputs"]["brainstorm"] == str((tmp_path / "asic" / "m").resolve())


def test_inject_sim_run_key_and_guard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Verification" / "simulation-triage" / "runs" / "1"
    wd.mkdir(parents=True)
    store.write_dispatch("m", "simulation-triage", wd, params={"sim_run": "3"})
    sim_root = str((tmp_path / "asic" / "m" / "Verification" / "simulation").resolve())
    assert _read(wd)["inputs"]["sim_run"] == sim_root + "/runs/3"


def test_narrowing_keys_absent_when_empty(tmp_path, monkeypatch):
    """`inputs` is always there; a narrowing key is written only when it carries something.
    Their ABSENCE is what a worker reads to tell a narrowed round from a full one, so an
    empty list must not serialize as a present-but-empty key."""
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Design" / "synthesis" / "runs" / "1"
    wd.mkdir(parents=True)
    store.write_dispatch("m", "synthesis", wd, None, [], [], [])
    assert list(_read(wd)) == ["inputs"]


def test_narrowing_keys_written_when_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wd = tmp_path / "asic" / "m" / "Design" / "rtl-design" / "runs" / "2"
    wd.mkdir(parents=True)
    store.write_dispatch(
        "m",
        "rtl-design",
        wd,
        None,
        ["Design/specification/child_a.md", "mac.v:42"],
        ["Design/synthesis/runs/1/result.json"],
        ["the area target's unit was wrong, not the RTL"],
    )
    doc = _read(wd)
    assert doc["scope"] == ["Design/specification/child_a.md", "mac.v:42"]
    assert doc["caused_by"] == ["Design/synthesis/runs/1/result.json"]
    assert doc["reasons"] == ["the area target's unit was wrong, not the RTL"]


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1/../2", "../9"])
def test_resolve_sim_run_rejects(tmp_path, bad):
    with pytest.raises(ValueError):
        store._resolve_sim_run(Path(tmp_path) / "asic" / "m", bad)
