# tests/unit/test_defaults_thresholds.py
"""defaults.yaml gate dimension set: structural-only (line/cond/fsm/toggle), no functional."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "skills/simulation/defaults.yaml"


def _thresholds():
    """coverage_thresholds block from defaults.yaml (dim -> number)."""
    data = yaml.safe_load(DEFAULTS.read_text()) or {}
    return data.get("coverage_thresholds") or {}


def test_gate_dims_are_structural_only():
    t = _thresholds()
    assert set(t) == {"line", "cond", "fsm", "toggle"}


def test_thresholds_are_numeric_and_achievable():
    t = _thresholds()
    # achievable per forensic anchors; fsm must still exceed run2's present-but-shallow ceiling (36%).
    assert t["fsm"] >= 40 and t["line"] >= 70
    assert all(isinstance(v, (int, float)) for v in t.values())
