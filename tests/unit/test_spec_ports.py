"""Tests for derive-ports — inter-module port derivation from interconnects.json."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"


def _run(workdir, check=True):
    return subprocess.run(
        ["python3", str(MAIN), "derive-ports", "--workdir", str(workdir)],
        capture_output=True,
        text=True,
        check=check,
    )


def _write_workdir(tmp_path, manifest, wires):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "interconnects.json").write_text(json.dumps(wires))


def _wire(name, producers, consumers, width=1):
    return {
        "wire": name,
        "producers": producers,
        "consumers": consumers,
        "width": width,
        "clock_domain": "clk",
    }


WIRES = [
    _wire("cmd_valid", ["ctrl"], ["dp"]),
    _wire("result", ["alu"], ["ctrl"]),
    _wire("dbg", ["ctrl"], ["ctrl"]),
]


def test_derives_cut_edges(tmp_path):
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [
                {"name": "ctrl", "doc": "ctrl.md", "rtl_modules": ["ctrl"]},
                {"name": "dp", "doc": "dp.md", "rtl_modules": ["dp", "alu"]},
            ],
        },
        WIRES,
    )
    out = json.loads(_run(tmp_path).stdout)
    # ctrl: producer of cmd_valid + dbg, consumer of result + dbg
    assert out["ctrl"] == ["cmd_valid", "dbg", "result"]
    # dp owns {dp, alu}: dp consumes cmd_valid, alu produces result
    assert out["dp"] == ["cmd_valid", "result"]


def test_empty_interconnects_yields_empty_ports(tmp_path):
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [{"name": "solo", "doc": "solo.md", "rtl_modules": ["solo"]}],
        },
        [],
    )
    out = json.loads(_run(tmp_path).stdout)
    assert out["solo"] == []


def test_missing_rtl_modules_fails_loud(tmp_path):
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [{"name": "x", "doc": "x.md"}],  # no rtl_modules
        },
        WIRES,
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "rtl_modules" in proc.stderr


def test_malformed_interconnects_fails_loud(tmp_path):
    """A mistyped key must stop the verb, not yield an empty cut-edge list: this output is
    injected into the wave-2 child prompts and runs before the design.md gate."""
    bad = [{**_wire("cmd_valid", ["ctrl"], ["dp"]), "widht": 1}]
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [{"name": "ctrl", "doc": "ctrl.md", "rtl_modules": ["ctrl"]}],
        },
        bad,
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "widht" in proc.stderr and "interconnects.json" in proc.stderr


def test_missing_required_field_fails_loud(tmp_path):
    bad = [
        {k: v for k, v in _wire("cmd_valid", ["ctrl"], ["dp"]).items() if k != "width"}
    ]
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [{"name": "ctrl", "doc": "ctrl.md", "rtl_modules": ["ctrl"]}],
        },
        bad,
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0 and "width" in proc.stderr


def test_missing_children_fails_clean(tmp_path):
    """A manifest without 'children' must fail loud with a clean message, not a KeyError."""
    _write_workdir(tmp_path, {"module": "m"}, WIRES)
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "children" in proc.stderr
    assert "Traceback" not in proc.stderr
