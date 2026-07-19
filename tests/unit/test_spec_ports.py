"""Tests for derive-ports — inter-module port derivation from §1.4.2."""

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


def _write_workdir(tmp_path, manifest, design):
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "design.md").write_text(design)


DESIGN = (
    "# m Design\n\n"
    "#### 1.4.2 Inter-module Interconnects\n\n"
    "| Wire | Producer (RTL module) | Consumer (RTL module) | Protocol |\n"
    "|------|-----------------------|-----------------------|----------|\n"
    "| cmd_valid | ctrl | dp | vr |\n"
    "| result | alu | ctrl | vr |\n"
    "| dbg | ctrl | ctrl | tap |\n"
)


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
        DESIGN,
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
        "# m\n\n#### 1.4.2 Inter-module Interconnects\n\n(none — N=1)\n",
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
        DESIGN,
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "rtl_modules" in proc.stderr


def test_142_drifted_header_fails_loud(tmp_path):
    """§1.4.2 table with 'Signal' instead of 'Wire' must fail loud, not yield empty ports."""
    drifted_design = (
        "# m Design\n\n"
        "#### 1.4.2 Inter-module Interconnects\n\n"
        "| Signal | Producer (RTL module) | Consumer (RTL module) | Protocol |\n"
        "|--------|------------------------|------------------------|----------|\n"
        "| cmd_valid | ctrl | dp | vr |\n"
    )
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [{"name": "ctrl", "doc": "ctrl.md", "rtl_modules": ["ctrl"]}],
        },
        drifted_design,
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "1.4.2" in proc.stderr
    assert "Wire" in proc.stderr


def test_142_missing_endpoint_column_fails_loud(tmp_path):
    """§1.4.2 table missing a Producer/Consumer column must fail loud, not silently
    yield empty ports (same class of drift as a mis-named Wire column)."""
    drifted_design = (
        "# m Design\n\n"
        "#### 1.4.2 Inter-module Interconnects\n\n"
        "| Wire | Producer | Consumer | Protocol |\n"
        "|------|----------|----------|----------|\n"
        "| cmd_valid | ctrl | dp | vr |\n"
    )
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [{"name": "ctrl", "doc": "ctrl.md", "rtl_modules": ["ctrl"]}],
        },
        drifted_design,
    )
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "1.4.2" in proc.stderr


def test_142_column_guard_uses_header_not_ragged_row0(tmp_path):
    """F5-consistency: the §1.4.2 column guard checks the declared HEADER, not the first
    data row — a complete header with a ragged first data row must not false-report a
    missing canonical column."""
    design = (
        "# m Design\n\n#### 1.4.2 Inter-module Interconnects\n\n"
        "| Wire | Producer (RTL module) | Consumer (RTL module) | Protocol |\n"
        "|------|------------------------|------------------------|----------|\n"
        "| cmd_valid | ctrl |\n"  # ragged: 2 cells under a 4-column header
    )
    _write_workdir(
        tmp_path,
        {
            "module": "m",
            "children": [{"name": "ctrl", "doc": "ctrl.md", "rtl_modules": ["ctrl"]}],
        },
        design,
    )
    proc = _run(tmp_path, check=False)
    assert "missing canonical column" not in proc.stderr


def test_missing_children_fails_clean(tmp_path):
    """A manifest without 'children' must fail loud with a clean message, not a KeyError."""
    _write_workdir(tmp_path, {"module": "m"}, DESIGN)
    proc = _run(tmp_path, check=False)
    assert proc.returncode != 0
    assert "children" in proc.stderr
    assert "Traceback" not in proc.stderr
