# tests/unit/test_rtl_conformance.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/rtl-design/scripts/rtl/__main__.py"
sys.path.insert(0, str(ROOT / "skills/rtl-design/scripts"))


def _ann(sgdc=None, sdc=None):
    """The full 7-category annotation shape the schema requires, with overrides."""
    return {
        "sgdc": {
            "sync_cell": [],
            "reset_synchronizer": [],
            "set_case_analysis": [],
            "quasi_static": [],
            **(sgdc or {}),
        },
        "sdc": {
            "create_generated_clock": [],
            "set_multicycle_path": [],
            "set_false_path": [],
            **(sdc or {}),
        },
    }


def _write_state(d, ledger):
    """rtl-design's two sidecars from the merged {child: {files, incdirs?, annotations}} shape."""
    import json as _json

    files, anns = {}, {}
    for name, rec in ledger.items():
        e = {"files": rec.get("files", [])}
        if rec.get("incdirs"):
            e["incdirs"] = rec["incdirs"]
        files[name] = e
        anns[name] = rec.get("annotations", {})
    (d / "rtl-files.json").write_text(_json.dumps(files))
    (d / "constraint-annotations.json").write_text(_json.dumps(anns))


def _setup(tmp_path, children, ledger, files, wires=None):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"module": "top", "children": children})
    )
    _write_state(tmp_path, ledger)
    (tmp_path / "interconnects.json").write_text(json.dumps(wires or []))
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
            "--interconnects",
            str(tmp_path / "interconnects.json"),
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
            "leaf": {"files": ["leaf.v"], "annotations": _ann()},
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {
            "leaf.v": "module leaf_m(input a); endmodule\n",
            "top.v": "module top(input a); leaf_m u_leaf(.a(a)); endmodule\n",
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
            "leaf": {"files": ["leaf.v"], "annotations": _ann()},
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {
            "leaf.v": "module WRONG_NAME(input a); endmodule\n",
            "top.v": "module top(input a); endmodule\n",
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
            "leaf": {"files": ["leaf.v"], "annotations": _ann()},
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {
            "leaf.v": 'module pre; initial $display("/* %d", x); endmodule\n'
            "module clkdiv; endmodule\n"
            'module post; initial $display("end */ y"); endmodule\n',
            "top.v": "module top; clkdiv u0(); endmodule\n",
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
                "files": ["leaf.v"],
                "annotations": _ann(sgdc={"sync_cell": ["sync2"]}),
            },
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {
            "leaf.v": "module leaf_m; endmodule\nmodule sync2; endmodule\n",
            "top.v": "module top; leaf_m u0(); sync2 u1(); endmodule\n",
        },
    )  # instantiate siblings so the top-integration reachability check is clean
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
                "files": ["leaf.v"],
                "annotations": _ann(sgdc={"sync_cell": ["sync_GHOST"]}),
            },
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {"leaf.v": "module leaf_m; endmodule\n", "top.v": "module top; endmodule\n"},
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
                "files": ["leaf.v"],
                "annotations": _ann(
                    sdc={
                        "create_generated_clock": [
                            {"module": "clkdiv_GHOST", "pin": "q"}
                        ]
                    }
                ),
            },
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {"leaf.v": "module leaf_m; endmodule\n", "top.v": "module top; endmodule\n"},
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
                "files": ["leaf.v"],
                "annotations": _ann(sgdc={"sync_cell": ["sync2"]}),
            },
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {
            "leaf.v": "module leaf_m; endmodule\n// module sync2; endmodule\n",
            "top.v": "module top; endmodule\n",
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
                "files": ["leaf.v"],
                "annotations": _ann(sgdc={"reset_synchronizer": ["rsync_GHOST"]}),
            },
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {"leaf.v": "module leaf_m; endmodule\n", "top.v": "module top; endmodule\n"},
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    assert any(
        x["annotation"] == "reset_synchronizer" and x["name"] == "rsync_GHOST"
        for x in json.loads(r.stdout)["violations"]
    )


_WIRES_WITH_BUS_READY = [
    {
        "wire": "bus_ready",
        "producers": ["leaf_m"],
        "consumers": ["top"],
        "width": 1,
        "clock_domain": "clk",
    }
]


def test_top_integration_pass(tmp_path):
    _setup(
        tmp_path,
        [
            {"name": "leaf", "rtl_modules": ["leaf_m"]},
            {"name": "topc", "rtl_modules": ["top"]},
        ],
        {
            "leaf": {"files": ["leaf.v"], "annotations": _ann()},
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {
            "leaf.v": "module leaf_m(output bus_ready); endmodule\n",
            "top.v": "module top; wire bus_ready; leaf_m u_leaf(.bus_ready(bus_ready)); endmodule\n",
        },
        wires=_WIRES_WITH_BUS_READY,
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
            "leaf": {"files": ["leaf.v"], "annotations": _ann()},
            "topc": {"files": ["top.v"], "annotations": _ann()},
        },
        {
            "leaf.v": "module leaf_m(output bus_ready); endmodule\n",
            "top.v": "module top; endmodule\n",
        },  # neither instantiates leaf_m nor has bus_ready net
        wires=_WIRES_WITH_BUS_READY,
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
            "topc": {"files": ["top.v"], "annotations": _ann()},
            "c1": {"files": ["c1.v"], "annotations": _ann()},
            "c2": {"files": ["c2.v"], "annotations": _ann()},
        },
        {
            "top.v": "module top; modA a(); endmodule\n",
            "c1.v": "module modA; endmodule\nmodule modB; modZ z(); endmodule\n",
            "c2.v": "module modZ; endmodule\n",
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
        {"only": {"files": ["top.v"], "annotations": _ann()}},
        {"top.v": "module top(input a); endmodule\n"},
        wires=[],  # N=1: no inter-module wires
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert json.loads(r.stdout)["violations"] == []


# --- strict Verilog-2001 dialect gate (check_dialect) ---


def test_dialect_sv_extension_fails(tmp_path):
    # A .sv artifact passes presence/integration, but the kernel's downstream `*.v` selectors
    # cannot match it (the run-1 pipeline deadlock); the dialect gate rejects the extension.
    _setup(
        tmp_path,
        [{"name": "only", "rtl_modules": ["top"]}],
        {"only": {"files": ["top.sv"], "annotations": _ann()}},
        {"top.sv": "module top(input a); endmodule\n"},
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    v = json.loads(r.stdout)
    assert v["status"] == "fail"
    assert any(
        x["kind"] == "dialect" and x["file"] == "top.sv" and x["child"] == "only"
        for x in v["violations"]
    )


def test_dialect_gate_judges_the_extension_not_the_content(tmp_path):
    # The gate used to scan 27 SystemVerilog-only reserved words inside .v files. It no longer
    # does, and this pins that deliberately rather than leaving it to drift back: a `.v` file
    # matches the kernel's `*.v` selectors whatever it contains — which is the entire failure
    # the gate exists to prevent — and every downstream tool is configured to accept
    # SystemVerilog (`analyze -format sverilog`, `vcs -sverilog`, SpyGlass `language_mode
    # mixed`). A 27-word blacklist also could not stand in for a ~250-word language: a sample
    # of 47 equally common SV-only words slipped past 43 of them. Writing V2001 stays a coding
    # rule; it is not something this gate can decide.
    _setup(
        tmp_path,
        [{"name": "only", "rtl_modules": ["top"]}],
        {"only": {"files": ["top.v"], "annotations": _ann()}},
        {
            "top.v": "module top(input clk); logic q; always_ff @(posedge clk) q <= 1'b0; endmodule\n"
        },
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not any(x["kind"] == "dialect" for x in json.loads(r.stdout)["violations"])


def test_dialect_v_vh_and_support_files_pass(tmp_path):
    # Clean V2001: a .v source + a .vh header + a non-HDL support file (.mem) — the header is
    # allowed and the support file is out of scope, so none is flagged.
    _setup(
        tmp_path,
        [{"name": "only", "rtl_modules": ["top"]}],
        {"only": {"files": ["top.v", "defs.vh", "rom.mem"], "annotations": _ann()}},
        {
            "top.v": '`include "defs.vh"\nmodule top(input a); reg [7:0] r; endmodule\n',
            "defs.vh": "`define W 8\n",
            "rom.mem": "DEADBEEF\n",
        },
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert not any(x["kind"] == "dialect" for x in json.loads(r.stdout)["violations"])


def test_interconnect_wires_needs_no_placeholder_exemption():
    # An N=1 module writes an empty array, so there is no placeholder row to exempt — and
    # therefore no looser second clause that could quietly drop a real wire whose name
    # happens to contain the placeholder's text.
    from rtl.conformance import _interconnect_wires

    assert _interconnect_wires([]) == []
    assert _interconnect_wires(
        [{"wire": "bus_n=1_sel", "producers": ["p"], "consumers": ["c"]}]
    ) == ["bus_n=1_sel"]
