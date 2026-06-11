"""Tests for derive_plan_data.py — extracts the derived universe (features, interfaces,
clocks, scenarios, check_hints) from a spec workdir into plan-data.json."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/simulation-plan/scripts/derive_plan_data.py"

DESIGN_MD = """# m Design Document (design.md)

## 1. Module Overview

### 1.3 Feature Table

| ID | Feature | Description |
|----|---------|-------------|
| F-00 | cfg | config write |

#### 1.4.1 Top-Level IO

| Signal | Direction | Width | Clock Domain | Interface Group | Protocol | Role | ResetPolarity | ResetKind |
|--------|-----------|-------|--------------|-----------------|----------|------|---------------|-----------|
| clk | input | 1 | clk | cfg | - | clock | - | - |
| rst_n | input | 1 | clk | cfg | - | reset | 0 | async |
| wdata | input | 32 | clk | cfg | - | data | - | - |

### 1.6 Clocks and Frequencies

| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Generated | Role |
|------------|-------------------------|-----------------|--------------|-----------|------|
| clk | 100 | 10.0 | primary | no | primary clock |
"""

CHILD_MD = """# core

## §5 Verification Hints (9 columns required)

| CheckID | SourceFeature | ImplementationDetail | ImplementationDetailVerbatim | BrainstormAnchor | Observable | ReferenceRule | Latency | ResetBehavior |
|---------|---------------|----------------------|------------------------------|------------------|------------|---------------|---------|---------------|
| CHK-00 | F-00 | write reg | reg[addr] <= wdata | L12 | rdata | reg[addr]=wdata | 1 | 0 |
"""


def _workdir(tmp_path):
    (tmp_path / "design.md").write_text(DESIGN_MD)
    (tmp_path / "core.md").write_text(CHILD_MD)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "m", "children": [{"name": "core", "doc": "core.md"}]})
    )
    return tmp_path


def _run(workdir):
    subprocess.run(
        ["python3", str(SCRIPT), "--workdir", str(workdir)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads((workdir / "plan-data.json").read_text())


def test_interface_role_carried(tmp_path):
    pd = _run(_workdir(tmp_path))
    roles = {s["signal_name"]: s["role"] for s in pd["interfaces"]}
    assert roles == {"clk": "clock", "rst_n": "reset", "wdata": "data"}


def test_clock_relationship_carried(tmp_path):
    pd = _run(_workdir(tmp_path))
    assert pd["clocks"][0]["relationship"] == "primary"


def test_verbatim_extracted_risk_and_anchor_absent(tmp_path):
    pd = _run(_workdir(tmp_path))
    h = pd["check_hints"][0]
    assert h["implementation_detail_verbatim"] == "reg[addr] <= wdata"
    assert h["implementation_detail"] == "write reg"
    assert "risk" not in h
    assert "brainstorm_anchor" not in h


def test_idempotent_no_authored_state(tmp_path):
    wd = _workdir(tmp_path)
    first = _run(wd)
    second = _run(wd)
    assert first == second
