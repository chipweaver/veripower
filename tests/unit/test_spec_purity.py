"""Tests for check_purity — the top-partition invariant, at specification's partition gate.

"Exactly one child covers <TOP>, and that child's rtl_modules == [<TOP>]" is decided here and
nowhere else: rtl-design used to re-decide it at its own exit gate, which could only fire when
this gate had been bypassed and could only produce a failure rtl-design was unable to repair.
The partition gate is the last moment the partition is still editable, so it is the only place
the rule earns its round.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "specification" / "scripts"))
from spec.ports import check_purity  # noqa: E402

TOP = "tpu_top"


def _child(name, rtl_modules):
    return {"name": name, "doc": f"{name}.md", "rtl_modules": rtl_modules}


# (label, children, holds) — each case is a distinct way the invariant can hold or break.
CASES = [
    ("pure top plus leaves", [_child("mac", ["mac"]), _child("topc", [TOP])], True),
    ("single pure top only", [_child("topc", [TOP])], True),
    ("no child covers top", [_child("mac", ["mac"])], False),
    ("two children cover top", [_child("a", [TOP]), _child("b", [TOP])], False),
    ("top child bundles logic", [_child("topc", [TOP, "mac"])], False),
    ("top child bundles logic, top second", [_child("topc", ["mac", TOP])], False),
    ("empty roster", [], False),
    ("child with no rtl_modules key", [{"name": "x", "doc": "x.md"}], False),
]


@pytest.mark.parametrize("label,children,holds", CASES, ids=[c[0] for c in CASES])
def test_check_purity_verdict(label, children, holds):
    violations = check_purity({"module": TOP, "children": children})
    assert (violations == []) is holds, f"{label}: {violations}"


def test_an_absent_module_key_is_a_routable_violation():
    # check_purity is the gate that makes an absent manifest.module impossible downstream, so
    # reporting it is its job alone — every later reader indexes the key.
    violations = check_purity({"children": [_child("topc", [TOP])]})
    assert len(violations) == 1
    assert "module" in violations[0]
