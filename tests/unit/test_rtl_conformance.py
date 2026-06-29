# tests/unit/test_rtl_conformance.py
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
_ANN = {"sgdc": {}, "sdc": {}}


def _setup(
    tmp_path, children, ledger, files, design="## §1.4.2 Inter-module Interconnects\n"
):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "top", "children": children})
    )
    (tmp_path / ".child_reports.json").write_text(json.dumps(ledger))
    (tmp_path / "design.md").write_text(design)
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def _run(tmp_path, top="top"):
    return subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-conformance",
            "--workdir",
            str(tmp_path),
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--top",
            top,
            "--ledger",
            str(tmp_path / ".child_reports.json"),
            "--design",
            str(tmp_path / "design.md"),
        ],
        capture_output=True,
        text=True,
    )


def test_module_presence_pass(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {
            "leaf.sv": "module leaf_m(input a); endmodule\n",
            "top.sv": "module top(input a); leaf_m u_leaf(.a(a)); endmodule\n",
        },
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "pass"


def test_module_presence_missing_fails(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {
            "leaf.sv": "module WRONG_NAME(input a); endmodule\n",
            "top.sv": "module top(input a); endmodule\n",
        },
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    v = json.loads(r.stdout)
    assert v["status"] == "fail"
    assert any(
        x["kind"] == "module_presence"
        and x["missing_module"] == "leaf_m"
        and x["child"] == "leaf"
        for x in v["violations"]
    )
    assert "leaf" in v["fail_reason"]


def test_string_embedded_comment_markers_do_not_swallow_real_decl(tmp_path):
    # a `/*` and `*/` inside string literals must NOT eat a real module decl between them
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["clkdiv"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {
            "leaf.sv": 'module pre; initial $display("/* %d", x); endmodule\n'
            "module clkdiv; endmodule\n"
            'module post; initial $display("end */ y"); endmodule\n',
            "top.sv": "module top; clkdiv u0(); endmodule\n",
        },
    )
    r = _run(tmp_path)
    assert not any(
        x["kind"] == "module_presence" and x["missing_module"] == "clkdiv"
        for x in json.loads(r.stdout)["violations"]
    )


def test_child_absent_from_ledger_is_silently_skipped(tmp_path):
    _setup(
        tmp_path,
        [{"name": "leaf", "rtl_modules": ["leaf_m"]}],
        {},  # ledger has no entry for "leaf"
        {},
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert json.loads(r.stdout)["violations"] == []


def test_annotation_reality_pass(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m", "sync2"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {
                "files": ["leaf.sv"],
                "annotations": {"sgdc": {"sync_cell": ["sync2"]}, "sdc": {}},
            },
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {
            "leaf.sv": "module leaf_m; endmodule\nmodule sync2; endmodule\n",
            "top.sv": "module top; leaf_m u0(); sync2 u1(); endmodule\n",
        },
    )  # instantiate siblings so check_top_integration is clean once Task 3 lands
    r = _run(tmp_path)
    assert r.returncode == 0
    assert json.loads(r.stdout)["violations"] == []


def test_annotation_reality_phantom_name_fails(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {
                "files": ["leaf.sv"],
                "annotations": {"sgdc": {"sync_cell": ["sync_GHOST"]}, "sdc": {}},
            },
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {"leaf.sv": "module leaf_m; endmodule\n", "top.sv": "module top; endmodule\n"},
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    v = json.loads(r.stdout)
    assert any(
        x["kind"] == "annotation_reality"
        and x["name"] == "sync_GHOST"
        and x["annotation"] == "sync_cell"
        for x in v["violations"]
    )


def test_annotation_reality_create_generated_clock_phantom_fails(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {
                "files": ["leaf.sv"],
                "annotations": {
                    "sgdc": {},
                    "sdc": {
                        "create_generated_clock": [
                            {"module": "clkdiv_GHOST", "pin": "q"}
                        ]
                    },
                },
            },
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {"leaf.sv": "module leaf_m; endmodule\n", "top.sv": "module top; endmodule\n"},
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert any(
        x["annotation"] == "create_generated_clock" and x["name"] == "clkdiv_GHOST"
        for x in json.loads(r.stdout)["violations"]
    )


def test_annotation_reality_commented_decl_does_not_satisfy(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {
                "files": ["leaf.sv"],
                "annotations": {"sgdc": {"sync_cell": ["sync2"]}, "sdc": {}},
            },
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {
            "leaf.sv": "module leaf_m; endmodule\n// module sync2; endmodule\n",
            "top.sv": "module top; endmodule\n",
        },
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert any(
        x["annotation"] == "sync_cell" and x["name"] == "sync2"
        for x in json.loads(r.stdout)["violations"]
    )


def test_annotation_reality_reset_synchronizer_phantom_fails(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {
                "files": ["leaf.sv"],
                "annotations": {
                    "sgdc": {"reset_synchronizer": ["rsync_GHOST"]},
                    "sdc": {},
                },
            },
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {"leaf.sv": "module leaf_m; endmodule\n", "top.sv": "module top; endmodule\n"},
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert any(
        x["annotation"] == "reset_synchronizer" and x["name"] == "rsync_GHOST"
        for x in json.loads(r.stdout)["violations"]
    )


_DESIGN_WITH_WIRE = (
    "## §1.4.2 Inter-module Interconnects\n\n"
    "| Wire | Producer | Consumer | Width |\n"
    "|---|---|---|---|\n"
    "| bus_ready | leaf_m | top | 1 |\n"
)


def test_top_integration_pass(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {
            "leaf.sv": "module leaf_m(output bus_ready); endmodule\n",
            "top.sv": "module top; wire bus_ready; leaf_m u_leaf(.bus_ready(bus_ready)); endmodule\n",
        },
        design=_DESIGN_WITH_WIRE,
    )
    r = _run(tmp_path)
    assert r.returncode == 0


def test_top_integration_missing_instance_and_wire_fails(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"files": ["leaf.sv"], "annotations": _ANN},
            "topc": {"files": ["top.sv"], "annotations": _ANN},
        },
        {
            "leaf.sv": "module leaf_m(output bus_ready); endmodule\n",
            "top.sv": "module top; endmodule\n",
        },  # neither instantiates leaf_m nor has bus_ready net
        design=_DESIGN_WITH_WIRE,
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    v = json.loads(r.stdout)
    kinds = {
        (x["kind"], x.get("missing_module") or x.get("missing_wire"))
        for x in v["violations"]
    }
    assert ("top_instantiation", "leaf_m") in kinds
    assert ("interconnect_wire", "bus_ready") in kinds
    assert all(x["child"] == "topc" for x in v["violations"])
    inst = next(x for x in v["violations"] if x["kind"] == "top_instantiation")
    assert inst["owner_child"] == "leaf"


def test_top_integration_reachability_is_child_grained(tmp_path):
    # PRESENCE-PROXY CEILING (documented): reachability is computed at OWNER-CHILD
    # granularity, not per-module. A child that authors both a reachable module and an
    # orphan module leaks the orphan's instantiations onto the use-graph — so a module
    # instantiated ONLY by the orphan is still seen as reachable. We pin this: modB (the
    # orphan itself) IS flagged; modZ (reachable only via the orphan) is NOT. A truly
    # dangling modZ is caught downstream by lint-cdc / synthesis elaboration.
    _setup(
        tmp_path,
        [
            {"name": "topc", "rtl_modules": ["top"]},
            {"name": "c1", "rtl_modules": ["modA", "modB"]},
            {"name": "c2", "rtl_modules": ["modZ"]},
        ],
        {
            "topc": {"files": ["top.sv"], "annotations": _ANN},
            "c1": {"files": ["c1.sv"], "annotations": _ANN},
            "c2": {"files": ["c2.sv"], "annotations": _ANN},
        },
        {
            "top.sv": "module top; modA a(); endmodule\n",
            "c1.sv": "module modA; endmodule\nmodule modB; modZ z(); endmodule\n",
            "c2.sv": "module modZ; endmodule\n",
        },
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    orphans = {
        x["missing_module"]
        for x in json.loads(r.stdout)["violations"]
        if x["kind"] == "top_instantiation"
    }
    assert "modB" in orphans  # the orphan module is flagged
    assert (
        "modZ" not in orphans
    )  # child-grained ceiling: instantiated only by the orphan


def test_single_child_is_top_no_violations(tmp_path):
    _setup(
        tmp_path,
        [{"name": "only", "rtl_modules": ["top"]}],
        {"only": {"files": ["top.sv"], "annotations": _ANN}},
        {"top.sv": "module top(input a); endmodule\n"},
        design=(
            "## §1.4.2 Inter-module Interconnects\n\n| Wire | Producer | Consumer | Width |\n"
            "|---|---|---|---|\n| (none — N=1 module has no inter-module wires) | - | - | - |\n"
        ),
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert json.loads(r.stdout)["violations"] == []
