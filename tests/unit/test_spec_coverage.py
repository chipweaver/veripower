# tests/unit/test_spec_coverage.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"
sys.path.insert(0, str(ROOT / "skills/specification/scripts"))
from spec.coverage import compute_anchor_resolvability, parse_anchor  # noqa: E402


def test_parse_anchor_single_range():
    assert parse_anchor("lines 5-10", 100) == [(5, 10)]


def test_parse_anchor_to_end():
    assert parse_anchor("lines 5-end", 100) == [(5, 100)]


def test_parse_anchor_multi_range():
    # F1: a child legitimately spanning two disjoint brainstorm regions
    assert parse_anchor("lines 5-10, 20-30", 100) == [(5, 10), (20, 30)]


def test_parse_anchor_d4_literal():
    # A well-formed anchor claiming no lines: the empty list, NOT None. None is reserved
    # for unparseable, and the caller turns None into a gate-failing orphan.
    assert parse_anchor("D4-architecture-only", 100) == []
    assert parse_anchor("D4-architecture-only", 100) is not None


def test_parse_anchor_garbage():
    assert parse_anchor("nonsense", 100) is None


# ── anchor resolvability: the gating reviewer's read-scope must resolve ────────
# The spec-review faithfulness lens reads brainstorm.md at this anchor. An anchor that does
# not resolve makes a GATING reviewer judge a child against blank or wrong text and report
# "no findings" — silent in the direction that matters. This check assumes nothing about the
# brainstorm's shape, which is why it survived the cut that removed the three checks that did.


def _man(*anchors):
    return {
        "module": "m",
        "children": [
            {
                "name": f"c{i}",
                "doc": f"c{i}.md",
                "rtl_modules": [f"c{i}"],
                "brainstorm_anchor": a,
            }
            for i, a in enumerate(anchors)
        ],
    }


def _bs(n):
    return "\n".join(f"line {i}" for i in range(1, n + 1))


def test_anchor_resolvability_clean():
    r = compute_anchor_resolvability(_man("lines 1-40", "lines 41-100"), _bs(100))
    assert r == {"violations": []}


def test_anchor_out_of_bounds_is_a_violation():
    # Previously reachable but untested: the branch that catches an anchor pointing past the
    # end of the file. A reviewer given lines 82-160 of a 109-line brainstorm reads a short
    # tail and calls it the intent.
    r = compute_anchor_resolvability(_man("lines 82-160"), _bs(109))
    assert len(r["violations"]) == 1
    assert "does not resolve" in r["violations"][0]["error"]
    assert "109-line" in r["violations"][0]["error"]


def test_anchor_unparseable_is_a_violation():
    r = compute_anchor_resolvability(_man("total garbage, not a range"), _bs(100))
    assert len(r["violations"]) == 1 and "unparseable" in r["violations"][0]["error"]


def test_anchor_inverted_range_is_a_violation():
    # A reversed range yields an empty slice, so the reviewer reads nothing and finds nothing.
    r = compute_anchor_resolvability(_man("lines 40-10"), _bs(100))
    assert (
        len(r["violations"]) == 1 and "does not resolve" in r["violations"][0]["error"]
    )


def test_anchor_zero_start_is_a_violation():
    r = compute_anchor_resolvability(_man("lines 0-10"), _bs(100))
    assert len(r["violations"]) == 1


def test_architecture_only_child_claims_nothing_and_is_allowed():
    # It declares descent from the architecture partitioning rather than from any passage —
    # the one anchor for which an empty slice is the correct answer.
    r = compute_anchor_resolvability(_man("D4-architecture-only"), _bs(100))
    assert r == {"violations": []}


def test_anchors_need_not_cover_the_brainstorm():
    # Deliberate: the removed gap check demanded every chapter be claimed, which on a real
    # module needed a hand-written exemption list naming 5 of 9 chapters. Uncovered lines are
    # not a defect — the reviewer reads the whole document regardless.
    r = compute_anchor_resolvability(_man("lines 1-5"), _bs(500))
    assert r == {"violations": []}


def test_every_child_is_checked_not_just_the_first():
    r = compute_anchor_resolvability(
        _man("lines 1-10", "nonsense", "lines 900-999"), _bs(100)
    )
    assert [v["child"] for v in r["violations"]] == ["c1", "c2"]


# ---------- structure gate ----------

# compute_structure reads every input out of the workdir's sidecars, so the helpers below
# need a throwaway workdir to hold them.
_DEFAULT_CLOCKS = [
    {
        "name": "clk",
        "freq_mhz": 100,
        "period_ns": 10.0,
        "relationship": "primary",
        "role": "primary clock",
    }
]
_NO_CLOCKS = object()  # sentinel: write no clocks.json at all

_DEFAULT_FEATURES = [
    {
        "id": "F-00",
        "name": "f",
        "description": "d",
        "mode_interface": "cfg",
        "priority": "smoke",
        "happy_path": "h",
        "corner_cases": "c",
        "negative_cases": "n",
    }
]


_DEFAULT_SCENARIOS = [
    {
        "id": "SC-0",
        "stimulus": "write",
        "expected": "ack",
        "timing_constraint": "T_setup",
    }
]


def _port(name, direction, role, domain="clk", width=1, group="cfg", **kw):
    e = {
        "name": name,
        "direction": direction,
        "width": width,
        "clock_domain": domain,
        "interface_group": group,
        "role": role,
    }
    e.update(kw)
    return e


_DEFAULT_PORTS = [
    _port("clk", "input", "clock"),
    _port("din", "input", "data", width=8),
]
_DEFAULT_WIRES: list = []


def _clocks_wd(clocks=None, features=None, ports=None, wires=None):
    """A throwaway specification workdir holding the sidecars compute_structure reads."""
    import json
    import tempfile

    d = Path(tempfile.mkdtemp())
    if clocks is not _NO_CLOCKS:
        (d / "clocks.json").write_text(
            json.dumps(_DEFAULT_CLOCKS if clocks is None else clocks)
        )
    (d / "features.json").write_text(
        json.dumps(_DEFAULT_FEATURES if features is None else features)
    )
    (d / "timing-scenarios.json").write_text(json.dumps(_DEFAULT_SCENARIOS))
    (d / "top-io.json").write_text(
        json.dumps(_DEFAULT_PORTS if ports is None else ports)
    )
    (d / "interconnects.json").write_text(
        json.dumps(_DEFAULT_WIRES if wires is None else wires)
    )
    return d


def _struct(manifest=None, clocks=None, features=None, ports=None, wires=None):
    from spec import coverage as cc

    manifest = manifest or {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    return cc.compute_structure(_clocks_wd(clocks, features, ports, wires), manifest)


def test_structure_clean_passes():
    s = _struct()
    assert all(not v for v in s.values()), s


def test_structure_rb_period_freq_mismatch():
    # 1000/100 = 10, not 8 — the one clock check the schema cannot express.
    bad = [{**_DEFAULT_CLOCKS[0], "period_ns": 8.0}]
    assert _struct(clocks=bad)["period_violations"]


def test_structure_rf_clock_domain_not_in_clocks_json():
    bad = [
        _port("clk", "input", "clock"),
        _port("din", "input", "data", domain="clk_x"),
    ]
    assert _struct(ports=bad)["clock_domain_violations"]


def test_structure_children_zero_fails():
    s = _struct(manifest={"module": "m", "children": []})
    assert s["manifest_violations"]


def test_structure_no_clocks_json_does_not_cascade_domain_violations():
    # With clocks.json absent, do NOT emit a spurious clock_domain_violation for every
    # §1.4.1 row — that absence is derive-constraints' fail-loud to report.
    s = _struct(clocks=_NO_CLOCKS)
    assert s["clock_domain_violations"] == []


_DEFAULT_HINTS = [
    {
        "check_id": "CHK-0",
        "source_feature": "F-00",
        "implementation_detail": "sum",
        "observable": "y",
        "reference_rule": "rm",
    }
]


def _struct_with_children(
    child_bodies, clocks=None, features=None, hints=None, ports=None, wires=None
):
    import json

    from spec import coverage as cc

    children = [{"name": n, "doc": f"{n}.md", "rtl_modules": [n]} for n in child_bodies]
    manifest = {"module": "m", "children": children}
    wd = _clocks_wd(clocks, features, ports, wires)
    hd = wd / "check-hints"
    hd.mkdir(exist_ok=True)
    for n in child_bodies:
        (hd / f"{n}.json").write_text(
            json.dumps(_DEFAULT_HINTS if hints is None else hints)
        )
    return cc.compute_structure(wd, manifest, child_texts=child_bodies)


# The gate reads a child body as free text (token presence), never as a table. Keep the
# fixture shaped like a real child doc: §5 is a pointer to check-hints/<child>.json.
_CHILD_5 = "## §5 Verification Hints\n\nSee `check-hints/c.json`.\n"


def test_rc_uncovered_feature_fails():
    # features.json has F-00; the child's hints reference only F-99 → F-00 uncovered
    orphan = [{**_DEFAULT_HINTS[0], "source_feature": "F-99"}]
    s = _struct_with_children({"c": _CHILD_5}, hints=orphan)
    assert any("F-00" in g["feature_id"] for g in s["feature_coverage_gaps"])


def test_rc_covered_feature_passes():
    bodies = {"c": _CHILD_5}  # references F-00
    s = _struct_with_children(bodies)
    assert s["feature_coverage_gaps"] == []


def test_child_hint_missing_required_field_fails():
    lean = [{k: v for k, v in _DEFAULT_HINTS[0].items() if k != "reference_rule"}]
    s = _struct_with_children({"c": _CHILD_5}, hints=lean)
    v = s["hint_column_violations"]
    assert v and v[0]["child"] == "c" and "reference_rule" in v[0]["error"]


def test_child_hint_misspelled_key_fails():
    bad = [{**_DEFAULT_HINTS[0], "obserable": "y"}]
    s = _struct_with_children({"c": _CHILD_5}, hints=bad)
    v = s["hint_column_violations"]
    assert v and "obserable" in v[0]["error"]


def test_structure_clean_with_children_passes():
    # A fully-formed design + a conformant child §5 yields zero violations in ALL keys.
    s = _struct_with_children({"c": _CHILD_5})
    assert all(not v for v in s.values()), s


def test_frontmatter_missing_required_key_fails(tmp_path):
    from spec import coverage as cc

    # child frontmatter missing `parent` and `clocks`
    (tmp_path / "c.md").write_text(
        '---\nchild: c\nbrainstorm_anchor: "lines 1-3"\nports: []\nfeatures: []\n---\nbody\n',
        encoding="utf-8",
    )
    manifest = {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    fs = cc.compute_frontmatter_subset(tmp_path, manifest)
    missing = {m["child"]: set(m["missing"]) for m in fs["missing_keys"]}
    assert "c" in missing and {"parent", "clocks"} <= missing["c"]


def test_frontmatter_all_required_keys_present_passes(tmp_path):
    from spec import coverage as cc

    (tmp_path / "c.md").write_text(
        '---\nchild: c\nparent: m\nbrainstorm_anchor: "lines 1-3"\n'
        "ports: []\nclocks: []\nfeatures: []\n---\nbody\n",
        encoding="utf-8",
    )
    manifest = {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    fs = cc.compute_frontmatter_subset(tmp_path, manifest)
    assert fs["missing_keys"] == []


def test_end_to_end_multi_child_clean_workdir(tmp_path):
    """End-to-end: a clean N=2 workdir passes the whole coverage gate (all five
    sub-blocks), incl. a pure top-integration child (core_top, rtl_modules==[core])
    and a multi-RTL-per-child unit (core_b owns 2 rtl_modules)."""
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "core",
                "children": [
                    {
                        "name": "core_top",
                        "doc": "core_top.md",
                        "rtl_modules": ["core"],
                        "brainstorm_anchor": "lines 1-3",
                    },
                    {
                        "name": "core_b",
                        "doc": "core_b.md",
                        "rtl_modules": ["core_b", "core_b_alu"],
                        "brainstorm_anchor": "lines 4-6",
                    },
                ],
            }
        )
    )
    (tmp_path / "features.json").write_text(json.dumps(_DEFAULT_FEATURES))
    (tmp_path / "clocks.json").write_text(json.dumps(_DEFAULT_CLOCKS))
    (tmp_path / "timing-scenarios.json").write_text(json.dumps(_DEFAULT_SCENARIOS))
    (tmp_path / "top-io.json").write_text(json.dumps(_DEFAULT_PORTS))
    (tmp_path / "interconnects.json").write_text(json.dumps(_DEFAULT_WIRES))
    child = (
        '---\nchild: {n}\nparent: core\nbrainstorm_anchor: "{a}"\n'
        "ports: []\nclocks: []\nfeatures:\n  - F-00\n---\n\n"
        "## §5 Verification Hints\n\nSee `check-hints/{n}.json`.\n"
    )
    (tmp_path / "core_top.md").write_text(child.format(n="core_top", a="lines 1-3"))
    (tmp_path / "core_b.md").write_text(child.format(n="core_b", a="lines 4-6"))
    hd = tmp_path / "check-hints"
    hd.mkdir()
    for n in ("core_top", "core_b"):
        (hd / f"{n}.json").write_text(json.dumps(_DEFAULT_HINTS))
    bs = tmp_path / "brainstorm.md"
    bs.write_text("# A\nx\n## B\ny\n## C\nz\n")
    proc = subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-coverage",
            "--workdir",
            str(tmp_path),
            "--brainstorm",
            str(bs),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    cov = json.loads(proc.stdout)
    assert cov["status"] == "pass"
    assert set(cov) == {
        "status",
        "anchor_resolvability",
        "frontmatter_subset",
        "structure",
    }


def test_end_to_end_impure_top_child_fails(tmp_path):
    """A manifest whose top-integration child bundles a logic module fails the gate
    at the specification stage (purity_violations folded into the structure sub-block)."""
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "module": "core",
                "children": [
                    {
                        "name": "core_top",
                        "doc": "core_top.md",
                        "rtl_modules": [
                            "core",
                            "core_b_alu",
                        ],  # bundles a logic module -> impure
                        "brainstorm_anchor": "lines 1-6",
                    }
                ],
            }
        )
    )
    child = (
        '---\nchild: core_top\nparent: core\nbrainstorm_anchor: "lines 1-6"\n'
        "ports: []\nclocks: []\nfeatures:\n  - F-00\n---\n\n"
        "## §5 Verification Hints\n\nSee `check-hints/core_top.json`.\n"
    )
    (tmp_path / "core_top.md").write_text(child)
    bs = tmp_path / "brainstorm.md"
    bs.write_text("# A\nx\n## B\ny\n## C\nz\n")
    proc = subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-coverage",
            "--workdir",
            str(tmp_path),
            "--brainstorm",
            str(bs),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    cov = json.loads(proc.stdout)
    assert cov["status"] == "fail"
    assert cov["structure"]["purity_violations"], cov["structure"]
    assert cov["structure"]["purity_violations"][0]["child"] == "core_top"


# ---------- purity gate ----------


def test_purity_pure_top_child():
    from spec import coverage as cc

    m = {
        "module": "top",
        "children": [
            {"name": "top", "rtl_modules": ["top"]},
            {"name": "alu", "rtl_modules": ["alu"]},
        ],
    }
    assert cc.compute_purity(m) == []


def test_purity_impure_top_child_bundles_leaf():
    from spec import coverage as cc

    m = {"module": "top", "children": [{"name": "core", "rtl_modules": ["top", "alu"]}]}
    v = cc.compute_purity(m)
    assert v and v[0]["child"] == "core" and v[0]["rtl_modules"] == ["top", "alu"]


def test_purity_miscovered_zero():
    from spec import coverage as cc

    m = {"module": "top", "children": [{"name": "a", "rtl_modules": ["a"]}]}
    v = cc.compute_purity(m)
    assert v and v[0]["covering_count"] == 0


def test_purity_miscovered_multiple():
    from spec import coverage as cc

    m = {
        "module": "top",
        "children": [
            {"name": "a", "rtl_modules": ["top"]},
            {"name": "b", "rtl_modules": ["top", "x"]},
        ],
    }
    v = cc.compute_purity(m)
    assert v and v[0]["covering_count"] == 2


def test_purity_n1_single_module_is_pure():
    from spec import coverage as cc

    m = {
        "module": "counter",
        "children": [{"name": "counter", "rtl_modules": ["counter"]}],
    }
    assert cc.compute_purity(m) == []


def test_purity_impure_top_child_with_clean_sibling():
    # realistic N>=2: a clean leaf coexists with an impure top child — pins that
    # compute_purity selects the covering child correctly among several.
    from spec import coverage as cc

    m = {
        "module": "core",
        "children": [
            {"name": "core_top", "rtl_modules": ["core", "alu"]},
            {"name": "alu", "rtl_modules": ["alu"]},
        ],
    }
    v = cc.compute_purity(m)
    assert v and v[0]["child"] == "core_top" and v[0]["rtl_modules"] == ["core", "alu"]


def test_purity_missing_module_field():
    # missing 'module' (the manifest SSoT top) must fail with a clear cause, not a
    # misattributed "covered by 0 children".
    from spec import coverage as cc

    m = {"children": [{"name": "c", "rtl_modules": ["c"]}]}
    v = cc.compute_purity(m)
    assert v and "missing required 'module'" in v[0]["error"]


# ---------- §1.4.2 interconnect completeness ----------


def test_interconnect_clean_passes():
    assert _struct()["interconnect_violations"] == []


def test_interconnect_missing_width_is_a_schema_violation():
    # Width presence moved into the schema; a wire without it never reaches the gate's
    # cross-file checks.
    bad = [
        {
            "wire": "score_S",
            "producers": ["a"],
            "consumers": ["b"],
            "clock_domain": "clk",
        }
    ]
    s = _struct(wires=bad)
    assert s["interconnects_schema_violations"]
    assert "width" in s["interconnects_schema_violations"][0]["error"]


def test_interconnect_clock_not_in_clocks_json():
    # Cross-file, so it stays in the gate: a phantom domain hides a CDC path.
    bad = [
        {
            "wire": "score_S",
            "producers": ["a"],
            "consumers": ["b"],
            "width": 32,
            "clock_domain": "clk_x",
        }
    ]
    iv = _struct(wires=bad)["interconnect_violations"]
    assert any(
        v.get("wire") == "score_S" and v.get("clock_domain") == "clk_x" for v in iv
    )


# ---------- §1.4.1 top-IO Owner (deterministic) ----------


def _io_fm(name, ports):
    plist = "".join(f"  - {p}\n" for p in ports)
    return (
        f'---\nchild: {name}\nparent: top\nbrainstorm_anchor: "lines 1-1"\n'
        f"ports:\n{plist}clocks: []\nfeatures: []\n---\nbody\n"
    )


_IO_MANIFEST = {
    "module": "top",
    "children": [
        {"name": "top", "doc": "top.md", "rtl_modules": ["top"]},
        {"name": "drv", "doc": "drv.md", "rtl_modules": ["drv"]},
        {"name": "other", "doc": "other.md", "rtl_modules": ["other"]},
    ],
}


def _driver(ports, bodies, manifest=None):
    from spec import coverage as cc

    return cc.compute_structure(
        _clocks_wd(ports=ports), manifest or _IO_MANIFEST, child_texts=bodies
    )["top_io_driver_violations"]


def _row(owner):
    """The clock port plus one output whose owner is under test."""
    out = _port("sig_o", "output", "data", width=8, group="g")
    if owner is not None:
        out["owner"] = owner
    return [_port("clk", "input", "clock"), out]


def test_driver_clean_leaf_owner():
    bodies = {
        "top": _io_fm("top", ["sig_o"]),
        "drv": _io_fm("drv", ["sig_o"]),
        "other": _io_fm("other", []),
    }
    assert _driver((_row("drv")), bodies) == []


def test_driver_owner_top_passes_deterministic():
    # Owner=top is a valid child that lists its boundary output → passes the gate.
    # The leaf-owner preference is documented guidance, not a deterministic block.
    bodies = {
        "top": _io_fm("top", ["sig_o"]),
        "drv": _io_fm("drv", []),
        "other": _io_fm("other", []),
    }
    assert _driver((_row("top")), bodies) == []


def test_driver_owner_missing_is_a_schema_violation():
    # if direction == output then owner — the schema says it, so the gate does not repeat
    # it; the gate only resolves an owner that IS present.
    from spec import coverage as cc

    bodies = {
        "top": _io_fm("top", ["sig_o"]),
        "drv": _io_fm("drv", ["sig_o"]),
        "other": _io_fm("other", []),
    }
    st = cc.compute_structure(
        _clocks_wd(ports=_row(None)), _IO_MANIFEST, child_texts=bodies
    )
    assert st["top_io_schema_violations"]
    assert "owner" in st["top_io_schema_violations"][0]["error"]
    assert st["top_io_driver_violations"] == []


def test_driver_owner_not_a_child():
    bodies = {
        "top": _io_fm("top", []),
        "drv": _io_fm("drv", []),
        "other": _io_fm("other", []),
    }
    v = _driver((_row("ghost")), bodies)
    assert any(
        x.get("signal") == "sig_o" and "not a manifest child" in x.get("error", "")
        for x in v
    )


def test_driver_owner_does_not_list_signal():
    bodies = {
        "top": _io_fm("top", []),
        "drv": _io_fm("drv", []),
        "other": _io_fm("other", []),
    }
    v = _driver((_row("drv")), bodies)
    assert any(
        x.get("signal") == "sig_o" and "does not list" in x.get("error", "") for x in v
    )


def test_driver_input_not_gated():
    # An input has no owner: which inputs a child reads is that child's own decision,
    # declared in its frontmatter, not a partition fact stated at the top.
    ports = [
        _port("clk", "input", "clock"),
        _port("in_i", "input", "data", width=8, group="g"),
    ]
    bodies = {
        "top": _io_fm("top", ["in_i"]),
        "drv": _io_fm("drv", ["in_i"]),
        "other": _io_fm("other", ["in_i"]),
    }
    assert _driver(ports, bodies) == []


def test_driver_skipped_without_child_texts():
    from spec import coverage as cc

    s = cc.compute_structure(
        _clocks_wd(ports=_row("drv")), _IO_MANIFEST
    )  # child_texts=None
    assert s["top_io_driver_violations"] == []


# ---------- F5: ragged first data row must not yield false missing_column ----------


# ---------- F6: missing 'children' manifest key must yield a clean verdict ----------


def test_missing_children_key_clean_verdict(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"module": "m"}))  # no children
    bs = tmp_path / "brainstorm.md"
    bs.write_text("# A\nx\n")
    proc = subprocess.run(
        [
            "python3",
            str(MAIN),
            "check-coverage",
            "--workdir",
            str(tmp_path),
            "--brainstorm",
            str(bs),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    cov = json.loads(proc.stdout)  # valid JSON on stdout ⇒ graceful, not a traceback
    assert cov["status"] == "fail"
    assert cov["structure"]["manifest_violations"], cov["structure"]


# ---------- F7: misnamed §1.3 ID column must fail loud ----------


# ---------- features.json contract ----------


def _validate_features(workdir, doc=None):
    import json

    from spec import coverage as cc

    if doc is not None:
        (workdir / "features.json").write_text(json.dumps(doc))
    return cc.validate_sidecar(workdir, "features.json")


def test_features_missing_is_reported(tmp_path):
    assert _validate_features(tmp_path) == [{"error": "features.json missing"}]


def test_features_misspelled_key_names_itself(tmp_path):
    v = _validate_features(tmp_path, [{**_DEFAULT_FEATURES[0], "happy_pat": "h"}])
    assert v and "happy_pat" in v[0]["error"]


def test_features_blank_required_field_rejected(tmp_path):
    # Every field is minLength 1: a blank one is a defect, not a default.
    v = _validate_features(tmp_path, [{**_DEFAULT_FEATURES[0], "happy_path": ""}])
    assert v and v[0]["at"].endswith(".happy_path")


def test_features_missing_required_field_rejected(tmp_path):
    lean = {k: v for k, v in _DEFAULT_FEATURES[0].items() if k != "priority"}
    v = _validate_features(tmp_path, [lean])
    assert v and "priority" in v[0]["error"]


def test_features_coverage_intent_optional(tmp_path):
    assert _validate_features(tmp_path, _DEFAULT_FEATURES) == []


def test_empty_features_json_is_a_schema_violation_not_a_coverage_gap():
    # minItems 1. With no ids to cover, feature_coverage_gaps must stay quiet rather than
    # blame the children for a defect that belongs to features.json.
    s = _struct_with_children({"c": _CHILD_5}, features=[])
    assert s["features_schema_violations"] and s["feature_coverage_gaps"] == []


# ---------- check-hints/<child>.json: the two cross-checks that follow it ----------


def _hints_workdir(tmp_path, hints, child_body="# c\n\nbody\n"):
    import json

    (tmp_path / "c.md").write_text(child_body)
    (tmp_path / "features.json").write_text(json.dumps(_DEFAULT_FEATURES))
    (tmp_path / "clocks.json").write_text(json.dumps(_DEFAULT_CLOCKS))
    (tmp_path / "timing-scenarios.json").write_text(json.dumps(_DEFAULT_SCENARIOS))
    hd = tmp_path / "check-hints"
    hd.mkdir(exist_ok=True)
    (hd / "c.json").write_text(json.dumps(hints))
    manifest = {"module": "m", "children": [{"name": "c", "doc": "c.md"}]}
    return tmp_path, manifest


# ---------- timing-scenarios.json contract ----------


def _validate_scenarios(workdir, doc=None):
    import json

    from spec import coverage as cc

    if doc is not None:
        (workdir / "timing-scenarios.json").write_text(json.dumps(doc))
    return cc.validate_sidecar(workdir, "timing-scenarios.json")


def test_scenarios_missing_is_reported(tmp_path):
    assert _validate_scenarios(tmp_path) == [{"error": "timing-scenarios.json missing"}]


def test_scenarios_misspelled_key_names_itself(tmp_path):
    v = _validate_scenarios(tmp_path, [{**_DEFAULT_SCENARIOS[0], "stimulis": "x"}])
    assert v and "stimulis" in v[0]["error"]


def test_scenarios_optional_fields_may_be_absent(tmp_path):
    assert _validate_scenarios(tmp_path, _DEFAULT_SCENARIOS) == []


def test_scenarios_blank_required_field_rejected(tmp_path):
    v = _validate_scenarios(tmp_path, [{**_DEFAULT_SCENARIOS[0], "expected": ""}])
    assert v and v[0]["at"].endswith(".expected")


# ---------- F8: §5 SourceFeature aliases are no longer honored ----------


def test_source_feature_alias_is_rejected_not_reinterpreted():
    # An aliased key is a schema violation, not a silently-tolerated spelling. The feature
    # also stays uncovered, so the defect surfaces twice rather than being papered over.
    aliased = [
        {
            **{k: v for k, v in _DEFAULT_HINTS[0].items() if k != "source_feature"},
            "sourcefeature": "F-00",
        }
    ]
    s = _struct_with_children({"c": _CHILD_5}, hints=aliased)
    assert s["hint_column_violations"]
    assert any(g["feature_id"] == "F-00" for g in s["feature_coverage_gaps"])
