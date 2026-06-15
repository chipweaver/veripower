# tests/unit/test_check_coverage.py
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/specification/scripts/check_coverage.py"
sys.path.insert(0, str(ROOT / "skills/specification/scripts"))
from check_coverage import parse_anchor  # noqa: E402


def test_parse_anchor_single_range():
    assert parse_anchor("lines 5-10", 100) == [(5, 10)]


def test_parse_anchor_to_end():
    assert parse_anchor("lines 5-end", 100) == [(5, 100)]


def test_parse_anchor_multi_range():
    # F1: a child legitimately spanning two disjoint brainstorm regions
    assert parse_anchor("lines 5-10, 20-30", 100) == [(5, 10), (20, 30)]


def test_parse_anchor_d4_literal():
    assert parse_anchor("D4-architecture-only", 100) is None


def test_parse_anchor_garbage():
    assert parse_anchor("nonsense", 100) is None


def test_token_survival_reads_each_child_once(tmp_path, monkeypatch):
    """Child files are read once, not once-per-token."""
    import check_coverage as cc

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


def test_parse_main_tables_wrong_header_is_loud(tmp_path):
    """A §1.4.1 with a non-template header must not silently yield zero ports."""
    import check_coverage as cc

    design = (
        "# m\n\n### 1.4.1 Top-Level IO\n\n"
        "| Bogus | Direction |\n|---|---|\n| clk | input |\n"
    )
    import pytest

    with pytest.raises(ValueError, match=r"1\.4\.1.*Signal"):
        cc.parse_main_design_tables(design)


def test_parse_main_tables_142_wrong_header_is_loud():
    """A §1.4.2 with a non-template header must not silently yield zero ports."""
    import check_coverage as cc
    import pytest

    design = (
        "# m\n\n### 1.4.2 Inter-module Interconnects\n\n"
        "| Signal | Producer (RTL module) | Consumer (RTL module) |\n"
        "|--------|------------------------|------------------------|\n"
        "| clk_en | ctrl | dp |\n"
    )
    with pytest.raises(ValueError, match=r"1\.4\.2.*Wire"):
        cc.parse_main_design_tables(design)


def test_parse_main_tables_16_wrong_header_is_loud():
    """A §1.6 with a non-template header must not silently yield zero clocks."""
    import check_coverage as cc
    import pytest

    design = (
        "# m\n\n### 1.6 Clocks and Freq\n\n"
        "| Name | Frequency |\n|------|----------|\n| sys_clk | 100 MHz |\n"
    )
    with pytest.raises(ValueError, match=r"1\.6.*Clock Name"):
        cc.parse_main_design_tables(design)


def _bs(manifest, brainstorm):
    import check_coverage as cc

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
    import check_coverage as cc

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
    import check_coverage as cc

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
    import check_coverage as cc

    (tmp_path / "c.md").write_text("ok body", encoding="utf-8")
    manifest = {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    design = "# m\nThe formula is defined; see brainstorm §sd_div for detail.\n"
    sc = cc.compute_self_containment(tmp_path, manifest, design)
    assert sc["by_reference_jumps"], "must flag 'see brainstorm'"


def test_self_containment_flags_cross_child_link(tmp_path):
    import check_coverage as cc

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
    import check_coverage as cc

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
    import check_coverage as cc

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
    import check_coverage as cc

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
    import check_coverage as cc

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
    "| ID | Feature | Description | Mode/Interface | Priority | HappyPath | CornerCases | NegativeCases |\n"
    "|----|---------|-------------|----------------|----------|-----------|-------------|---------------|\n"
    "| F-00 | f | d | cfg | smoke | h | c | n |\n\n"
    "#### 1.4.1 Top-Level IO\n\n"
    "| Signal | Direction | Width | Clock Domain | Interface Group | Protocol | Role |\n"
    "|--------|-----------|-------|--------------|-----------------|----------|------|\n"
    "| clk | input | 1 | clk | clk | - | clock |\n"
    "| din | input | 8 | clk | cfg | APB3 | data |\n\n"
    "#### 1.4.2 Inter-module Interconnects\n\n(none — N=1)\n\n"
    "### 1.5 Interface Timing Scenarios\n\n"
    "| ScenarioID | Interface/Mode | Trigger/Stimulus | Expected Result | Timing Constraint | Exceptions |\n"
    "|------------|----------------|------------------|-----------------|-------------------|------------|\n"
    "| SC-0 | cfg | write | ack | T_setup | none |\n\n"
    "### 1.6 Clocks and Frequencies\n\n"
    "| Clock Name | Nominal Frequency (MHz) | SDC Period (ns) | Relationship | Role |\n"
    "|------------|-------------------------|-----------------|--------------|------|\n"
    "| clk | 100 | 10.0 | primary | primary clock |\n"
)


def _struct(design, manifest=None):
    import check_coverage as cc

    manifest = manifest or {
        "module": "m",
        "children": [{"name": "c", "doc": "c.md", "rtl_modules": ["c"]}],
    }
    return cc.compute_structure(manifest, design)


def test_structure_clean_passes():
    s = _struct(_GOOD_DESIGN)
    assert all(not v for v in s.values()), s


def test_structure_missing_gated_column():
    bad = _GOOD_DESIGN.replace("| Priority ", "| ").replace("| smoke ", "| ")
    assert _struct(bad)["column_violations"]


def test_structure_rb_period_freq_mismatch():
    bad = _GOOD_DESIGN.replace("| 100 | 10.0 |", "| 100 | 8.0 |")  # 1000/100=10, not 8
    assert _struct(bad)["period_violations"]


def test_structure_rf_clock_domain_not_in_16():
    bad = _GOOD_DESIGN.replace(
        "| din | input | 8 | clk |", "| din | input | 8 | clk_x |"
    )
    assert _struct(bad)["clock_domain_violations"]


def test_structure_children_zero_fails():
    s = _struct(_GOOD_DESIGN, manifest={"module": "m", "children": []})
    assert s["manifest_violations"]


def test_structure_142_cross_reference_does_not_satisfy_presence():
    # a prose "see §1.4.2" without an actual §1.4.2 heading must still be flagged missing.
    no_142 = _GOOD_DESIGN.replace(
        "#### 1.4.2 Inter-module Interconnects\n\n(none — N=1)\n\n",
        "Note: see §1.4.2 elsewhere for Inter-module Interconnects.\n\n",
    )
    s = _struct(no_142)
    assert any("1.4.2" in p for p in s["presence_violations"])


def test_structure_no_16_does_not_cascade_domain_violations():
    # with §1.6 absent, do NOT emit spurious clock_domain_violations (the §1.6 absence
    # is caught by column/presence; the domain check must stay quiet).
    no_16 = _GOOD_DESIGN.split("### 1.6 Clocks and Frequencies")[0]
    s = _struct(no_16)
    assert s["clock_domain_violations"] == []
    assert s[
        "presence_violations"
    ]  # §1.6 absence still caught via presence ("§1.6 table missing or empty")


def _struct_with_children(design, child_bodies):
    import check_coverage as cc

    children = [{"name": n, "doc": f"{n}.md", "rtl_modules": [n]} for n in child_bodies]
    manifest = {"module": "m", "children": children}
    return cc.compute_structure(manifest, design, child_texts=child_bodies)


_CHILD_5 = (
    "## §5 Verification Hints\n\n"
    "| CheckID | SourceFeature | ImplementationDetail | Observable | ReferenceRule |\n"
    "|---------|---------------|----------------------|------------|---------------|\n"
    "| CHK-0 | F-00 | sum | y | rm |\n"
)


def test_rc_uncovered_feature_fails():
    # §1.3 has F-00; child §5 references only F-99 → F-00 uncovered
    bodies = {"c": _CHILD_5.replace("F-00", "F-99")}
    s = _struct_with_children(_GOOD_DESIGN, bodies)
    assert any("F-00" in g["feature_id"] for g in s["feature_coverage_gaps"])


def test_rc_covered_feature_passes():
    bodies = {"c": _CHILD_5}  # references F-00
    s = _struct_with_children(_GOOD_DESIGN, bodies)
    assert s["feature_coverage_gaps"] == []


def test_child_hint_missing_column_fails():
    bodies = {"c": _CHILD_5.replace("| ReferenceRule ", "| ")}
    s = _struct_with_children(_GOOD_DESIGN, bodies)
    assert s["hint_column_violations"]


def test_structure_clean_with_children_passes():
    # A fully-formed design + a conformant child §5 yields zero violations in ALL keys.
    s = _struct_with_children(_GOOD_DESIGN, {"c": _CHILD_5})
    assert all(not v for v in s.values()), s


def test_frontmatter_missing_required_key_fails(tmp_path):
    import check_coverage as cc

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
    import check_coverage as cc

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
    child = (
        '---\nchild: {n}\nparent: core\nbrainstorm_anchor: "{a}"\n'
        "ports: []\nclocks: []\nfeatures:\n  - F-00\n---\n\n"
        "## §5 Verification Hints\n\n"
        "| CheckID | SourceFeature | ImplementationDetail | Observable | ReferenceRule |\n"
        "|---|---|---|---|---|\n| CHK-0 | F-00 | sum | y | rm |\n"
    )
    (tmp_path / "core_top.md").write_text(child.format(n="core_top", a="lines 1-3"))
    (tmp_path / "core_b.md").write_text(child.format(n="core_b", a="lines 4-6"))
    bs = tmp_path / "brainstorm.md"
    bs.write_text("# A\nx\n## B\ny\n## C\nz\n")
    proc = subprocess.run(
        ["python3", str(SCRIPT), str(tmp_path), "--brainstorm", str(bs)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    cov = json.loads((tmp_path / "coverage.json").read_text())
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
        ["python3", str(SCRIPT), str(tmp_path), "--brainstorm", str(bs)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    cov = json.loads((tmp_path / "coverage.json").read_text())
    assert cov["status"] == "fail"
    assert cov["structure"]["purity_violations"], cov["structure"]
    assert cov["structure"]["purity_violations"][0]["child"] == "core_top"


# ---------- purity gate ----------


def test_purity_pure_top_child():
    import check_coverage as cc

    m = {
        "module": "top",
        "children": [
            {"name": "top", "rtl_modules": ["top"]},
            {"name": "alu", "rtl_modules": ["alu"]},
        ],
    }
    assert cc.compute_purity(m) == []


def test_purity_impure_top_child_bundles_leaf():
    import check_coverage as cc

    m = {"module": "top", "children": [{"name": "core", "rtl_modules": ["top", "alu"]}]}
    v = cc.compute_purity(m)
    assert v and v[0]["child"] == "core" and v[0]["rtl_modules"] == ["top", "alu"]


def test_purity_miscovered_zero():
    import check_coverage as cc

    m = {"module": "top", "children": [{"name": "a", "rtl_modules": ["a"]}]}
    v = cc.compute_purity(m)
    assert v and v[0]["covering_count"] == 0


def test_purity_miscovered_multiple():
    import check_coverage as cc

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
    import check_coverage as cc

    m = {
        "module": "counter",
        "children": [{"name": "counter", "rtl_modules": ["counter"]}],
    }
    assert cc.compute_purity(m) == []


def test_purity_impure_top_child_with_clean_sibling():
    # realistic N>=2: a clean leaf coexists with an impure top child — pins that
    # compute_purity selects the covering child correctly among several.
    import check_coverage as cc

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
    import check_coverage as cc

    m = {"children": [{"name": "c", "rtl_modules": ["c"]}]}
    v = cc.compute_purity(m)
    assert v and "missing required 'module'" in v[0]["error"]
