# tests/unit/test_spec_coverage.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "skills/specification/scripts/spec/__main__.py"
sys.path.insert(0, str(ROOT / "skills/specification/scripts"))
from spec.coverage import parse_anchor  # noqa: E402


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


def test_token_survival_reads_each_child_once(tmp_path, monkeypatch):
    """Child files are read once, not once-per-token."""
    from spec import coverage as cc

    child = tmp_path / "c.md"
    child.write_text("body without the tokens", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    brainstorm = (
        "assign a = b;\nassign c = d;\nassign e = f;\n"  # 3 distinct hard tokens
    )
    reads = {"n": 0}
    orig = Path.read_text

    def counting_read_text(self, *a, **k):
        if self.name == "c.md":
            reads["n"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    cc.compute_token_survival(tmp_path, manifest, brainstorm, "main design no tokens")
    assert reads["n"] == 1, f"child read {reads['n']}x; must be 1 (cached)"


def _bs(manifest, brainstorm):
    from spec import coverage as cc

    return cc.compute_brainstorm_coverage(manifest, brainstorm)


def test_brainstorm_coverage_only_gaps_and_orphans():
    bs = _bs(
        {
            "module": "m",
            "children": [
                {
                    "name": "c",
                    "doc": "c.md",
                    "rtl_modules": ["c"],
                    "brainstorm_anchor": "lines 1-5",
                }
            ],
        },
        "# A\n## B\nx\n## C\ny\n",
    )  # chapters A(1),B(2),C(4); child covers 1-5
    assert set(bs.keys()) == {"gaps", "orphans"}  # no covered_chapters / overlaps
    assert bs["gaps"] == [] and bs["orphans"] == []


def test_brainstorm_coverage_architecture_only_child_is_not_an_orphan():
    # child-design-template.md offers "D4-architecture-only" as a legal brainstorm_anchor,
    # for a child born of the architecture partitioning rather than of any one chapter. It
    # claims no lines by design, so it must not read as a broken anchor: an orphan fails the
    # whole gate, which would make such a module impossible to deliver.
    bs = _bs(
        {
            "module": "m",
            "children": [
                {
                    "name": "c",
                    "doc": "c.md",
                    "rtl_modules": ["c"],
                    "brainstorm_anchor": "lines 1-5",
                },
                {
                    "name": "m_top",
                    "doc": "m_top.md",
                    "rtl_modules": ["m"],
                    "brainstorm_anchor": "D4-architecture-only",
                },
            ],
        },
        "# A\n## B\nx\n## C\ny\n",
    )
    assert bs["orphans"] == []
    assert bs["gaps"] == []


def test_brainstorm_coverage_gap_detected():
    bs = _bs(
        {
            "module": "m",
            "children": [
                {
                    "name": "c",
                    "doc": "c.md",
                    "rtl_modules": ["c"],
                    "brainstorm_anchor": "lines 1-1",
                }
            ],
        },
        "# A\n## B\nx\n## C\ny\n",
    )  # C at line 4 unclaimed → gap
    assert "C" in bs["gaps"]


def test_brainstorm_coverage_nonshared_overlap_passes():
    # two children overlapping a shared cut-edge chapter must NOT fail
    bs = _bs(
        {
            "module": "m",
            "children": [
                {
                    "name": "a",
                    "doc": "a.md",
                    "rtl_modules": ["a"],
                    "brainstorm_anchor": "lines 1-4",
                },
                {
                    "name": "b",
                    "doc": "b.md",
                    "rtl_modules": ["b"],
                    "brainstorm_anchor": "lines 3-6",
                },
            ],
        },
        "# A\n## B\nx\n## C\ny\n## D\nz\n",
    )
    assert bs["gaps"] == [] and bs["orphans"] == []  # overlap is not a failure


def test_token_survival_catches_dropped_localparam(tmp_path):
    from spec import coverage as cc

    (tmp_path / "c.md").write_text("child body, no constants", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    brainstorm = "localparam DEPTH = 16;\nparameter WIDTH = 8;\n"
    tok = cc.compute_token_survival(
        tmp_path, manifest, brainstorm, "design.md without them"
    )
    missing = {m["missing_token"] for m in tok["missing_tokens"]}
    assert any("DEPTH" in m for m in missing)
    assert any("WIDTH" in m for m in missing)


def test_token_survival_param_survives(tmp_path):
    from spec import coverage as cc

    (tmp_path / "c.md").write_text("uses localparam DEPTH = 16; here", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    tok = cc.compute_token_survival(
        tmp_path, manifest, "localparam DEPTH = 16;\n", "main design"
    )
    assert tok["missing_tokens"] == []


def test_self_containment_flags_by_reference_jump(tmp_path):
    from spec import coverage as cc

    (tmp_path / "c.md").write_text("ok body", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    design = "# m\nThe formula is defined; see brainstorm §sd_div for detail.\n"
    sc = cc.compute_self_containment(tmp_path, manifest, design)
    assert sc["by_reference_jumps"], "must flag 'see brainstorm'"


def test_self_containment_flags_cross_child_link(tmp_path):
    from spec import coverage as cc

    (tmp_path / "a.md").write_text(
        "see the sibling [b](b.md) for the handshake", encoding="utf-8"
    )
    (tmp_path / "b.md").write_text("ok", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [
            {"name": "a", "doc": "a.md", "rtl_modules": ["a"]},
            {"name": "b", "doc": "b.md", "rtl_modules": ["b"]},
        ],
    }
    sc = cc.compute_self_containment(tmp_path, manifest, "# m clean")
    assert sc["cross_child_links"], "must flag a→b.md link"


def test_self_containment_clean(tmp_path):
    from spec import coverage as cc

    (tmp_path / "a.md").write_text(
        "self-contained; links only to [design](design.md)", encoding="utf-8"
    )
    manifest = {
        "module": "m",
        "children": [{"name": "a", "doc": "a.md", "rtl_modules": ["a"]}],
    }
    sc = cc.compute_self_containment(tmp_path, manifest, "# m clean body")
    assert sc["by_reference_jumps"] == [] and sc["cross_child_links"] == []


def test_self_containment_design_to_child_link_allowed(tmp_path):
    # design.md (the parent overview/index) linking to a child is allowed — cross-child is children-only.
    from spec import coverage as cc

    (tmp_path / "a.md").write_text("clean child", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [{"name": "a", "doc": "a.md", "rtl_modules": ["a"]}],
    }
    sc = cc.compute_self_containment(
        tmp_path, manifest, "# m\nSee submodule [a](a.md).\n"
    )
    assert sc["cross_child_links"] == []


def test_self_containment_brainstorming_word_not_flagged(tmp_path):
    from spec import coverage as cc

    (tmp_path / "a.md").write_text("ok", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [{"name": "a", "doc": "a.md", "rtl_modules": ["a"]}],
    }
    # "refer to brainstorming ..." substring-matches "refer to brainstorm" without a
    # word boundary; the \b guard must reject it (else legit prose false-fails).
    sc = cc.compute_self_containment(
        tmp_path, manifest, "# m\nWe refer to brainstorming best practices here.\n"
    )
    assert sc["by_reference_jumps"] == []


def test_self_containment_direct_brainstorm_link_flagged(tmp_path):
    from spec import coverage as cc

    (tmp_path / "a.md").write_text(
        "for context [here](brainstorm.md)", encoding="utf-8"
    )
    manifest = {
        "module": "m",
        "children": [{"name": "a", "doc": "a.md", "rtl_modules": ["a"]}],
    }
    sc = cc.compute_self_containment(tmp_path, manifest, "# m clean")
    assert sc["by_reference_jumps"], "direct ](brainstorm.md) link must be flagged"


# ---------- structure gate ----------

_GOOD_DESIGN = (
    "# m Design\n\n"
    "### 1.3 Feature Table\n\n"
    "The feature list lives in `features.json`.\n\n"
    "#### 1.4.1 Top-Level IO\n\nPorts live in `top-io.json`.\n\n"
    "#### 1.4.2 Inter-module Interconnects\n\nWires live in `interconnects.json`.\n\n"
    "### 1.5 Interface Timing Scenarios\n\n"
    "Scenario rows live in `timing-scenarios.json`.\n\n"
    "### 1.6 Clocks and Frequencies\n\n"
    "Clock definitions live in `clocks.json` (the sole numeric + relationship source).\n"
)


# compute_structure reads clocks.json out of the workdir, so the in-memory-design helpers
# below need a throwaway workdir to hold it.
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


def _struct(design, manifest=None, clocks=None, features=None, ports=None, wires=None):
    from spec import coverage as cc

    manifest = manifest or {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    return cc.compute_structure(
        _clocks_wd(clocks, features, ports, wires), manifest, design
    )


def test_structure_clean_passes():
    s = _struct(_GOOD_DESIGN)
    assert all(not v for v in s.values()), s


def test_structure_rb_period_freq_mismatch():
    # 1000/100 = 10, not 8 — the one clock check the schema cannot express.
    bad = [{**_DEFAULT_CLOCKS[0], "period_ns": 8.0}]
    assert _struct(_GOOD_DESIGN, clocks=bad)["period_violations"]


def test_structure_rf_clock_domain_not_in_clocks_json():
    bad = [
        _port("clk", "input", "clock"),
        _port("din", "input", "data", domain="clk_x"),
    ]
    assert _struct(_GOOD_DESIGN, ports=bad)["clock_domain_violations"]


def test_structure_children_zero_fails():
    s = _struct(_GOOD_DESIGN, manifest={"module": "m", "children": []})
    assert s["manifest_violations"]


def test_structure_no_clocks_json_does_not_cascade_domain_violations():
    # With clocks.json absent, do NOT emit a spurious clock_domain_violation for every
    # §1.4.1 row — that absence is derive-constraints' fail-loud to report.
    s = _struct(_GOOD_DESIGN, clocks=_NO_CLOCKS)
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
    design, child_bodies, clocks=None, features=None, hints=None, ports=None, wires=None
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
    return cc.compute_structure(wd, manifest, design, child_texts=child_bodies)


_CHILD_5 = (
    "## §5 Verification Hints\n\n"
    "| CheckID | SourceFeature | ImplementationDetail | Observable | ReferenceRule |\n"
    "|---------|---------------|----------------------|------------|---------------|\n"
    "| CHK-0 | F-00 | sum | y | rm |\n"
)


def test_rc_uncovered_feature_fails():
    # features.json has F-00; the child's hints reference only F-99 → F-00 uncovered
    orphan = [{**_DEFAULT_HINTS[0], "source_feature": "F-99"}]
    s = _struct_with_children(_GOOD_DESIGN, {"c": _CHILD_5}, hints=orphan)
    assert any("F-00" in g["feature_id"] for g in s["feature_coverage_gaps"])


def test_rc_covered_feature_passes():
    bodies = {"c": _CHILD_5}  # references F-00
    s = _struct_with_children(_GOOD_DESIGN, bodies)
    assert s["feature_coverage_gaps"] == []


def test_child_hint_missing_required_field_fails():
    lean = [{k: v for k, v in _DEFAULT_HINTS[0].items() if k != "reference_rule"}]
    s = _struct_with_children(_GOOD_DESIGN, {"c": _CHILD_5}, hints=lean)
    v = s["hint_column_violations"]
    assert v and v[0]["child"] == "c" and "reference_rule" in v[0]["error"]


def test_child_hint_misspelled_key_fails():
    bad = [{**_DEFAULT_HINTS[0], "obserable": "y"}]
    s = _struct_with_children(_GOOD_DESIGN, {"c": _CHILD_5}, hints=bad)
    v = s["hint_column_violations"]
    assert v and "obserable" in v[0]["error"]


def test_structure_clean_with_children_passes():
    # A fully-formed design + a conformant child §5 yields zero violations in ALL keys.
    s = _struct_with_children(_GOOD_DESIGN, {"c": _CHILD_5})
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
    fs = cc.compute_frontmatter_subset(tmp_path, manifest, "# m\n")
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
    fs = cc.compute_frontmatter_subset(tmp_path, manifest, "# m\n")
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
    (tmp_path / "design.md").write_text(
        _GOOD_DESIGN
    )  # the module-level fixture from earlier tasks
    (tmp_path / "features.json").write_text(json.dumps(_DEFAULT_FEATURES))
    (tmp_path / "clocks.json").write_text(json.dumps(_DEFAULT_CLOCKS))
    (tmp_path / "timing-scenarios.json").write_text(json.dumps(_DEFAULT_SCENARIOS))
    (tmp_path / "top-io.json").write_text(json.dumps(_DEFAULT_PORTS))
    (tmp_path / "interconnects.json").write_text(json.dumps(_DEFAULT_WIRES))
    child = (
        '---\nchild: {n}\nparent: core\nbrainstorm_anchor: "{a}"\n'
        "ports: []\nclocks: []\nfeatures:\n  - F-00\n---\n\n"
        "## §5 Verification Hints\n\n"
        "| CheckID | SourceFeature | ImplementationDetail | Observable | ReferenceRule |\n"
        "|---|---|---|---|---|\n| CHK-0 | F-00 | sum | y | rm |\n"
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
    assert set(cov) >= {
        "brainstorm_coverage",
        "frontmatter_subset",
        "token_survival",
        "self_containment",
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
    (tmp_path / "design.md").write_text(_GOOD_DESIGN)
    child = (
        '---\nchild: core_top\nparent: core\nbrainstorm_anchor: "lines 1-6"\n'
        "ports: []\nclocks: []\nfeatures:\n  - F-00\n---\n\n"
        "## §5 Verification Hints\n\n"
        "| CheckID | SourceFeature | ImplementationDetail | Observable | ReferenceRule |\n"
        "|---|---|---|---|---|\n| CHK-0 | F-00 | sum | y | rm |\n"
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

_DESIGN_142 = (  # one fully-pinned §1.4.2 wire (Width + Clock Domain)
    "# m Design\n\n"
    "#### 1.4.2 Inter-module Interconnects\n\n"
    "| Wire | Producer (RTL module) | Consumer (RTL module) | Width | Clock Domain "
    "| Protocol | Timing Constraint | Notes |\n"
    "|------|-----------------------|-----------------------|-------|--------------"
    "|----------|-------------------|-------|\n"
    "| score_S | pe_array | row_reduce | 32 | clk | stream | t | fp32 |\n\n"
    "### 1.6 Clocks and Frequencies\n\n"
    "Clock definitions live in `clocks.json` (the sole numeric + relationship source).\n"
)


def test_interconnect_clean_passes():
    assert _struct(_DESIGN_142)["interconnect_violations"] == []


def test_interconnect_n1_none_is_clean():
    # _GOOD_DESIGN's §1.4.2 is the prose sentinel "(none — N=1)" with no table rows.
    assert _struct(_GOOD_DESIGN)["interconnect_violations"] == []


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
    s = _struct(_GOOD_DESIGN, wires=bad)
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
    iv = _struct(_GOOD_DESIGN, wires=bad)["interconnect_violations"]
    assert any(
        v.get("wire") == "score_S" and v.get("clock_domain") == "clk_x" for v in iv
    )


# ---------- §1.4.1 top-IO Owner (deterministic) ----------


_IO_DESIGN = "# m\n\n#### 1.4.1 Top-Level IO\n\nPorts live in `top-io.json`.\n"


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
        _clocks_wd(ports=ports),
        manifest or _IO_MANIFEST,
        _IO_DESIGN,
        child_texts=bodies,
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
        _clocks_wd(ports=_row(None)), _IO_MANIFEST, _IO_DESIGN, child_texts=bodies
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
        _clocks_wd(ports=_row("drv")), _IO_MANIFEST, _IO_DESIGN
    )  # child_texts=None
    assert s["top_io_driver_violations"] == []


# ── token-survival: PPA Targets chapter exemption (ppa.json single-home) ─────


def test_token_survival_ppa_targets_section_exempt(tmp_path):
    # a D6-only numeric like "0.5 ns" single-homes in ppa.json; demanding prose
    # survival would deadlock against the design-template §1.1 no-restatement rule
    from spec import coverage as cc

    manifest = {"module": "m", "children": []}
    brainstorm = (
        "# B\n\n## PPA Targets\n\n- timing slack target 0.5 ns\n\n## Document Control\n"
    )
    tok = cc.compute_token_survival(
        tmp_path, manifest, brainstorm, "main design, no tokens"
    )
    assert tok["missing_tokens"] == []


def test_token_survival_ppa_token_elsewhere_still_required(tmp_path):
    # only the PPA-chapter occurrence is exempt: the same token appearing in another
    # chapter is still extracted there and must survive into design.md ∪ children
    from spec import coverage as cc

    manifest = {"module": "m", "children": []}
    brainstorm = (
        "# B\n\n## Clocks and Reset\n\nsampling window is 0.5 ns\n\n"
        "## PPA Targets\n\n- slack target 0.5 ns\n"
    )
    tok = cc.compute_token_survival(tmp_path, manifest, brainstorm, "no tokens here")
    assert {"missing_token": "0.5 ns"} in tok["missing_tokens"]


# ---------- F4: duplicate brainstorm chapter titles must not mask an uncovered one ----------


def test_brainstorm_coverage_duplicate_title_not_masked():
    # two chapters share the title "Overview"; a child covering only the FIRST must not
    # mask the SECOND (uncovered) one — the title must still surface in gaps.
    bs = _bs(
        {
            "module": "m",
            "children": [
                {
                    "name": "c",
                    "doc": "c.md",
                    "rtl_modules": ["c"],
                    "brainstorm_anchor": "lines 1-3",
                }
            ],
        },
        "# Top\n## Overview\nbody\n## Middle\n## Overview\ntail\n",
    )  # Top(1),Overview(2) covered by 1-3; Middle(4),Overview(5) uncovered
    assert "Overview" in bs["gaps"], bs["gaps"]
    assert "Middle" in bs["gaps"], bs["gaps"]


# ---------- F5: ragged first data row must not yield false missing_column ----------


# ---------- F6: missing 'children' manifest key must yield a clean verdict ----------


def test_missing_children_key_clean_verdict(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"module": "m"}))  # no children
    (tmp_path / "design.md").write_text(_GOOD_DESIGN)
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
    s = _struct_with_children(_GOOD_DESIGN, {"c": _CHILD_5}, features=[])
    assert s["features_schema_violations"] and s["feature_coverage_gaps"] == []


# ---------- check-hints/<child>.json: the two cross-checks that follow it ----------


def _hints_workdir(tmp_path, hints, child_body="# c\n\nbody\n"):
    import json

    (tmp_path / "design.md").write_text(_GOOD_DESIGN)
    (tmp_path / "c.md").write_text(child_body)
    (tmp_path / "features.json").write_text(json.dumps(_DEFAULT_FEATURES))
    (tmp_path / "clocks.json").write_text(json.dumps(_DEFAULT_CLOCKS))
    (tmp_path / "timing-scenarios.json").write_text(json.dumps(_DEFAULT_SCENARIOS))
    hd = tmp_path / "check-hints"
    hd.mkdir(exist_ok=True)
    (hd / "c.json").write_text(json.dumps(hints))
    manifest = {"module": "m", "children": [{"name": "c", "doc": "c.md"}]}
    return tmp_path, manifest


def test_token_survival_reaches_into_check_hints(tmp_path):
    # implementation_detail_verbatim is where brainstorm RTL formulas land, and it left
    # <child>.md. A token present ONLY in the JSON must still count as survived.
    from spec import coverage as cc

    formula = "o_result <= (i_data * i_weight) + 32'd0"
    hints = [{**_DEFAULT_HINTS[0], "implementation_detail_verbatim": formula}]
    wd, manifest = _hints_workdir(tmp_path, hints)
    assert formula not in (wd / "c.md").read_text()
    assert formula not in (wd / "design.md").read_text()
    r = cc.compute_token_survival(wd, manifest, f"# bs\n{formula}\n", _GOOD_DESIGN)
    assert r["missing_tokens"] == []


def test_token_survival_still_fails_when_token_is_nowhere(tmp_path):
    from spec import coverage as cc

    wd, manifest = _hints_workdir(tmp_path, _DEFAULT_HINTS)
    r = cc.compute_token_survival(
        wd, manifest, "# bs\nassign q = 8'hFF;\n", _GOOD_DESIGN
    )
    assert r["missing_tokens"]


def test_self_containment_scans_check_hints(tmp_path):
    # A by-reference jump is the same defect wherever it is written, so the scan followed
    # the hints out of <child>.md.
    from spec import coverage as cc

    hints = [{**_DEFAULT_HINTS[0], "implementation_detail": "see brainstorm §mac"}]
    wd, manifest = _hints_workdir(tmp_path, hints)
    r = cc.compute_self_containment(wd, manifest, _GOOD_DESIGN)
    assert any("check-hints/c.json" in v["file"] for v in r["by_reference_jumps"])


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
    s = _struct_with_children(_GOOD_DESIGN, {"c": _CHILD_5}, hints=aliased)
    assert s["hint_column_violations"]
    assert any(g["feature_id"] == "F-00" for g in s["feature_coverage_gaps"])


# ---------- F9: cross-child link detection with directory-prefixed docs ----------


def test_self_containment_cross_child_link_with_dir_prefixed_doc(tmp_path):
    from spec import coverage as cc

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.md").write_text("see sibling [b](b.md)", encoding="utf-8")
    (tmp_path / "sub" / "b.md").write_text("ok", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [
            {"name": "a", "doc": "sub/a.md", "rtl_modules": ["a"]},
            {"name": "b", "doc": "sub/b.md", "rtl_modules": ["b"]},
        ],
    }
    sc = cc.compute_self_containment(tmp_path, manifest, "# m clean")
    assert sc["cross_child_links"], (
        "must detect cross-child link with dir-prefixed docs"
    )
