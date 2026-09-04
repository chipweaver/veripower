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
_ROWS = [
    {"id": "R-00", "verbatim": "y follows the reference model", "judge": "simulation"},
    {"id": "R-01", "verbatim": "ports are Verilog-2001", "judge": "rtl-design"},
    {
        "id": "R-02",
        "verbatim": "line coverage above 90%",
        "judge": "simulation",
        "target": {"dim": "coverage_line", "op": ">", "value": 90},
    },
]
_HINTS = [
    {
        "check_id": "CHK-0",
        "requirements": ["R-00"],
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


def _fm(ports=(), clocks=()):
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
        + "---\n\n## §5 Verification Hints\n\nSee `check-hints/<child>.json`.\n"
    )


def _workdir(
    tmp_path, children=None, clocks=None, rows=None, ports=None, wires=None, hints=None
):
    """A complete N-child specification workdir. `children` maps child name -> frontmatter;
    `hints` maps child name -> its hints (a list applies to every child)."""
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
    (tmp_path / "requirements.json").write_text(
        json.dumps(_ROWS if rows is None else rows)
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
        h = (
            _HINTS
            if hints is None
            else (hints[n] if isinstance(hints, dict) else hints)
        )
        (hd / f"{n}.json").write_text(json.dumps(h))
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


def test_missing_frontmatter_key_is_reported(tmp_path):
    # An absent key would make its check pass vacuously, so presence is the guard.
    v = _verdict(tmp_path, children={"c": "---\nports: []\n---\n\nbody\n"})
    assert _said(v, "c.md frontmatter", "no 'clocks' key")


def test_port_clock_domain_not_in_clocks_json(tmp_path):
    bad = [
        _port("clk", "input", "clock"),
        _port("din", "input", "data", domain="clk_x"),
    ]
    v = _verdict(tmp_path, ports=bad)
    assert _said(v, "top-io.json din", "clock_domain 'clk_x' is not in clocks.json")


def test_wire_clock_domain_not_in_clocks_json(tmp_path):
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


# ---------- hints and the rows they name ----------


def test_hint_naming_a_row_the_ledger_lacks_is_reported(tmp_path):
    v = _verdict(tmp_path, hints=[{**_HINTS[0], "requirements": ["R-00", "R-99"]}])
    assert _said(
        v, "check-hints/c.json CHK-0", "'R-99', which requirements.json does not have"
    )


def test_hint_naming_a_row_another_stage_judges_is_reported(tmp_path):
    # A hint for a row rtl-design establishes would turn a requirement the engineer kept out
    # of the testbench into a gating check.
    v = _verdict(tmp_path, hints=[{**_HINTS[0], "requirements": ["R-00", "R-01"]}])
    assert _said(v, "check-hints/c.json CHK-0", "'R-01', which is not a simulation row")


def test_hint_naming_a_coverage_row_is_reported(tmp_path):
    # A coverage bound is compared by the coverage gate, not observed by a check.
    v = _verdict(tmp_path, hints=[{**_HINTS[0], "requirements": ["R-00", "R-02"]}])
    assert _said(v, "check-hints/c.json CHK-0", "'R-02', which is not a simulation row")


def test_simulation_row_no_hint_names_is_reported(tmp_path):
    rows = [
        *_ROWS,
        {"id": "R-03", "verbatim": "busy drops with done", "judge": "simulation"},
    ]
    v = _verdict(tmp_path, rows=rows)
    assert _said(v, "requirements.json R-03", "nothing verifies it")


def test_row_named_by_one_child_is_covered(tmp_path):
    # Emergent across children: the coverage is the union of what all of them wrote.
    rows = [
        *_ROWS,
        {"id": "R-03", "verbatim": "busy drops with done", "judge": "simulation"},
    ]
    hints = {
        "a": _HINTS,
        "b": [
            {
                "check_id": "CHK-1",
                "requirements": ["R-03"],
                "observable": "busy",
                "reference_rule": "rm",
            }
        ],
    }
    v = _verdict(tmp_path, children={"a": _fm(), "b": _fm()}, rows=rows, hints=hints)
    assert v["status"] == "pass", v


def test_duplicate_check_id_across_children_is_reported(tmp_path):
    v = _verdict(tmp_path, children={"a": _fm(), "b": _fm()})
    assert _said(v, "check-hints/b.json CHK-0", "already used in check-hints/a.json")


# ---------- outputs and their claimants ----------


def test_output_no_child_claims_is_reported(tmp_path):
    ports = [*_PORTS, _port("sig_o", "output", "data", width=8, group="g")]
    v = _verdict(tmp_path, ports=ports)
    assert _said(v, "top-io.json sig_o", "nothing drives it")


def test_output_claimed_by_a_child_passes(tmp_path):
    ports = [*_PORTS, _port("sig_o", "output", "data", width=8, group="g")]
    v = _verdict(tmp_path, children={"c": _fm(ports=["sig_o"])}, ports=ports)
    assert v["status"] == "pass", v


def test_multiple_claimants_are_not_asked_about(tmp_path):
    ports = [*_PORTS, _port("sig_o", "output", "data", width=8, group="g")]
    children = {"a": _fm(ports=["sig_o"]), "b": _fm(ports=["sig_o"])}
    hints = {"a": _HINTS, "b": []}
    v = _verdict(tmp_path, children=children, ports=ports, hints=hints)
    assert v["status"] == "pass", v


def test_an_unclaimed_input_is_not_reported(tmp_path):
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
    wd = _workdir(
        tmp_path,
        children={"core_top": _fm(), "core_b": _fm()},
        hints={"core_top": _HINTS, "core_b": []},
    )
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
    (wd / "requirements.json").write_text("[]")  # minItems 1
    proc = _run(wd)
    assert proc.returncode != 0
    assert "requirements.json" in (proc.stdout + proc.stderr)
