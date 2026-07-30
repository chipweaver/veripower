"""check-crossrefs: the join fan-out makes necessary.

One question, unanswerable by any single author: does what one file wrote agree with the file
that owns it. Each test asserts on the violation an agent actually reads — where + what — not
on an internal key, because that sentence IS the interface. A sidecar's own shape is not tested
here (read-time, see test_spec_sidecar.py) and neither is top-partition purity (decided at the
partition gate — test_spec_ports.py + the contract test).
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"
sys.path.insert(0, str(ROOT / "skills/specification/scripts"))

_CLOCKS = [{"name": "clk", "period_ns": 10.0, "relationship": "primary"}]
_FEATURES = [{"id": "F-00", "name": "f", "description": "d"}]
_HINTS = [
    {
        "check_id": "CHK-0",
        "source_feature": "F-00",
        "implementation_detail": "sum",
        "observable": "y",
        "reference_rule": "rm",
    }
]


def _port(name, direction, role, domain="clk", width=1, group="cfg"):
    return {
        "name": name,
        "direction": direction,
        "width": width,
        "clock_domain": domain,
        "interface_group": group,
        "role": role,
    }


_PORTS = [_port("clk", "input", "clock"), _port("din", "input", "data", width=8)]


def _fm(ports=(), clocks=(), features=("F-00",)):
    def block(key, items):
        return (
            f"{key}:\n" + "".join(f"  - {i}\n" for i in items)
            if items
            else f"{key}: []\n"
        )

    return (
        "---\n"
        + block("ports", ports)
        + block("clocks", clocks)
        + block("features", features)
        + "---\n\n## §5 Verification Hints\n\nSee `check-hints/<child>.json`.\n"
    )


def _workdir(
    tmp_path,
    children=None,
    clocks=None,
    features=None,
    ports=None,
    wires=None,
    hints=None,
):
    """A complete N-child specification workdir. `children` maps child name -> frontmatter."""
    children = {"c": _fm()} if children is None else children
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "m",
                "children": [
                    {"name": n, "doc": f"{n}.md", "rtl_modules": [n]} for n in children
                ],
            }
        )
    )
    (tmp_path / "clocks.json").write_text(
        json.dumps(_CLOCKS if clocks is None else clocks)
    )
    (tmp_path / "features.json").write_text(
        json.dumps(_FEATURES if features is None else features)
    )
    (tmp_path / "top-io.json").write_text(
        json.dumps(_PORTS if ports is None else ports)
    )
    (tmp_path / "interconnects.json").write_text(
        json.dumps([] if wires is None else wires)
    )
    hd = tmp_path / "check-hints"
    hd.mkdir(exist_ok=True)
    for n, body in children.items():
        (tmp_path / f"{n}.md").write_text(body)
        (hd / f"{n}.json").write_text(json.dumps(_HINTS if hints is None else hints))
    return tmp_path


def _verdict(tmp_path, **kw):
    from spec import crossrefs

    return crossrefs.verdict(_workdir(tmp_path, **kw))


def _said(v, where_frag, what_frag):
    """Did the verdict say this, in the words the agent reads?"""
    return [
        x
        for x in v["violations"]
        if where_frag in x["where"] and what_frag in x["what"]
    ]


# ---------- a name the owning file does not have ----------


def test_clean_workdir_passes(tmp_path):
    v = _verdict(tmp_path)
    assert v == {"status": "pass", "violations": []}


def test_child_port_not_in_any_boundary_sidecar(tmp_path):
    v = _verdict(tmp_path, children={"c": _fm(ports=["ghost"])})
    assert _said(v, "c.md frontmatter ports", "'ghost' is in neither top-io.json")


def test_child_port_may_name_an_interconnect_wire(tmp_path):
    wires = [
        {
            "wire": "score_S",
            "producers": ["a"],
            "consumers": ["b"],
            "width": 32,
            "clock_domain": "clk",
        }
    ]
    v = _verdict(tmp_path, children={"c": _fm(ports=["score_S"])}, wires=wires)
    assert v["status"] == "pass", v


def test_child_clock_not_in_clocks_json(tmp_path):
    v = _verdict(tmp_path, children={"c": _fm(clocks=["clk_x"])})
    assert _said(v, "c.md frontmatter clocks", "'clk_x' is not in clocks.json")


def test_child_feature_not_in_features_json(tmp_path):
    v = _verdict(tmp_path, children={"c": _fm(features=["F-00", "F-99"])})
    assert _said(v, "c.md frontmatter features", "'F-99' is not in features.json")


def test_missing_frontmatter_key_is_reported(tmp_path):
    # An absent key would make its check pass vacuously, so presence is the guard.
    body = "---\nports: []\nfeatures:\n  - F-00\n---\n\nbody\n"
    v = _verdict(tmp_path, children={"c": body})
    assert _said(v, "c.md frontmatter", "no 'clocks' key")


def test_port_clock_domain_not_in_clocks_json(tmp_path):
    bad = [
        _port("clk", "input", "clock"),
        _port("din", "input", "data", domain="clk_x"),
    ]
    v = _verdict(tmp_path, ports=bad)
    assert _said(v, "top-io.json din", "clock_domain 'clk_x' is not in clocks.json")


def test_wire_clock_domain_not_in_clocks_json(tmp_path):
    # A phantom interconnect domain hides a CDC path.
    bad = [
        {
            "wire": "score_S",
            "producers": ["a"],
            "consumers": ["b"],
            "width": 32,
            "clock_domain": "clk_x",
        }
    ]
    v = _verdict(tmp_path, wires=bad)
    assert _said(v, "interconnects.json score_S", "clock_domain 'clk_x' is not in")


# ---------- a target nothing refers to ----------


def test_feature_no_hint_references_is_reported(tmp_path):
    orphan = [{**_HINTS[0], "source_feature": "F-99"}]
    v = _verdict(tmp_path, hints=orphan)
    assert _said(v, "features.json F-00", "nothing verifies it")


def test_feature_referenced_by_one_child_is_covered(tmp_path):
    # Emergent across children: the coverage is the union of what all of them wrote.
    v = _verdict(tmp_path, children={"a": _fm(), "b": _fm()})
    assert v["status"] == "pass", v


def test_output_no_child_claims_is_reported(tmp_path):
    # The defect no single child's author can see: each knows only its own claim.
    ports = [*_PORTS, _port("sig_o", "output", "data", width=8, group="g")]
    v = _verdict(tmp_path, ports=ports)
    assert _said(v, "top-io.json sig_o", "nothing drives it")


def test_output_claimed_by_a_child_passes(tmp_path):
    ports = [*_PORTS, _port("sig_o", "output", "data", width=8, group="g")]
    v = _verdict(tmp_path, children={"c": _fm(ports=["sig_o"])}, ports=ports)
    assert v["status"] == "pass", v


def test_multiple_claimants_are_not_asked_about(tmp_path):
    # A top mux of N leaf sources and N leaves conflicting are indistinguishable from the
    # claims alone; that call belongs to a reader of the bodies.
    ports = [*_PORTS, _port("sig_o", "output", "data", width=8, group="g")]
    children = {"a": _fm(ports=["sig_o"]), "b": _fm(ports=["sig_o"])}
    v = _verdict(tmp_path, children=children, ports=ports)
    assert v["status"] == "pass", v


def test_an_unclaimed_input_is_not_reported(tmp_path):
    # Which inputs a child reads is its own decision, declared nowhere else.
    ports = [*_PORTS, _port("in_i", "input", "data", width=8, group="g")]
    v = _verdict(tmp_path, ports=ports)
    assert v["status"] == "pass", v


def test_every_disagreement_is_reported_not_just_the_first(tmp_path):
    v = _verdict(tmp_path, children={"c": _fm(ports=["ghost"], clocks=["clk_x"])})
    assert len(v["violations"]) == 2, v


# ---------- the verb ----------


def _run(workdir):
    return subprocess.run(
        ["python3", str(MAIN), "check-crossrefs", "--workdir", str(workdir)],
        capture_output=True,
        text=True,
    )


def test_verb_prints_the_verdict_and_exits_zero(tmp_path):
    wd = _workdir(tmp_path, children={"core_top": _fm(), "core_b": _fm()})
    proc = _run(wd)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout) == {"status": "pass", "violations": []}


def test_verb_exits_one_on_a_violation(tmp_path):
    wd = _workdir(tmp_path, children={"c": _fm(ports=["ghost"])})
    proc = _run(wd)
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "ghost" in proc.stdout


def test_verb_raises_on_a_malformed_sidecar(tmp_path):
    # Shape is a read-time defect, so it surfaces as the reader's error, not as a violation.
    wd = _workdir(tmp_path)
    (wd / "features.json").write_text("[]")  # minItems 1
    proc = _run(wd)
    assert proc.returncode != 0
    assert "features.json" in (proc.stdout + proc.stderr)
