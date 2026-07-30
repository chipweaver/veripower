"""The top-partition invariant is implemented twice; this locks the two together.

"Exactly one child covers <TOP>, and that child's rtl_modules == [<TOP>]" is decided by
`spec/ports.py:check_purity` (at specification's partition gate, the last moment the partition
is still editable) and again by `rtl/partition.py:coverage_verdict` (rtl-design's exit gate).
They agree today, and nothing else holds them there.

Extracting one implementation is NOT available: skills stay decoupled, so no cross-skill
import. A table both are run against is the only mechanism left, and it is enough: the two
must return the same verdict for the same manifest, so a divergence is a test failure
wherever it is introduced.

The one legitimate difference is the input contract, not the rule — check_purity reads TOP
from `manifest.module` and must report its absence, while coverage_verdict receives TOP as a
required CLI argument that cannot be empty. That case is asserted separately below.
"""

import json
import sys

import pytest
from _skills_sot import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "specification" / "scripts"))
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "rtl-design" / "scripts"))
from rtl.partition import coverage_verdict  # noqa: E402
from spec.ports import check_purity  # noqa: E402

TOP = "tpu_top"


def _child(name, rtl_modules):
    return {"name": name, "doc": f"{name}.md", "rtl_modules": rtl_modules}


# (label, children) — each case is a distinct way the invariant can hold or break.
CASES = [
    ("pure top plus leaves", [_child("mac", ["mac"]), _child("topc", [TOP])]),
    ("single pure top only", [_child("topc", [TOP])]),
    ("no child covers top", [_child("mac", ["mac"])]),
    ("two children cover top", [_child("a", [TOP]), _child("b", [TOP])]),
    ("top child bundles logic", [_child("topc", [TOP, "mac"])]),
    ("top child bundles logic, top listed second", [_child("topc", ["mac", TOP])]),
    ("empty roster", []),
    ("child with no rtl_modules key", [{"name": "x", "doc": "x.md"}]),
]


@pytest.mark.parametrize("label,children", CASES, ids=[c[0] for c in CASES])
def test_both_implementations_reach_the_same_verdict(label, children, tmp_path):
    manifest = {"module": TOP, "children": children}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    spec_violations = check_purity(manifest)
    rtl_status, rtl_reason = coverage_verdict(path, TOP)

    spec_pass = spec_violations == []
    rtl_pass = rtl_status == "pass"
    assert spec_pass == rtl_pass, (
        f"{label}: specification says {'pass' if spec_pass else 'fail'} while rtl-design says "
        f"{rtl_status} — the two implementations of the top-partition invariant have diverged "
        f"(spec: {spec_violations}; rtl: {rtl_reason})"
    )


def test_missing_module_is_the_one_asymmetry_and_it_is_the_input_contract():
    # check_purity resolves TOP itself, so an absent manifest.module is its problem to
    # report; coverage_verdict is handed TOP by a required CLI arg and never sees this case.
    # Asserted here so the asymmetry stays deliberate rather than becoming the first drift.
    violations = check_purity({"children": [_child("topc", [TOP])]})
    assert len(violations) == 1
    assert "module" in violations[0]
