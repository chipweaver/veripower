#!/usr/bin/env python3
"""check_coverage.py — manifest-driven coverage + token-survival verifier.

Writes `{workdir}/coverage.json` containing the `brainstorm_coverage`,
`frontmatter_subset`, and `token_survival` sub-blocks. (The former §3/§4
self-certification `fidelity_coverage` block is removed — those design.md sections
had no downstream consumer and were LLM-self-attested; token-survival replaces them
with an objective whole-brainstorm hard-token check.)

Usage: ``python3 check_coverage.py {workdir} --brainstorm <module-root-brainstorm.md>``
Exit: 0 if `status == "pass"`, 1 if `status == "fail"`.
"""

import json
import re
import sys
from pathlib import Path

import yaml

# ---------- brainstorm coverage ----------


def parse_brainstorm_chapters_with_depth(brainstorm_text: str):
    """Return list of `(line_no, header_title, depth)` for ATX headers."""
    chapters = []
    for i, line in enumerate(brainstorm_text.splitlines(), start=1):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            chapters.append((i, m.group(2), len(m.group(1))))
    return chapters


def parse_brainstorm_chapters(brainstorm_text: str):
    """Backwards-compatible wrapper returning `(line_no, title)` pairs."""
    return [
        (ln, t) for ln, t, _ in parse_brainstorm_chapters_with_depth(brainstorm_text)
    ]


def parse_anchor(anchor_str: str, brainstorm_lines: int):
    """Parse anchor; return a list of `(start, end)` ranges, or `None`.

    Caller writes an `orphans` entry with an `error` field when this
    returns `None`. Accepted forms:
      * ``lines X-Y``
      * ``lines X-end``
      * ``lines X-Y, X'-Y'`` (comma-separated disjoint ranges)
      * literal ``D4-architecture-only`` (→ None; caller records an orphan)
    """
    if anchor_str.strip() == "D4-architecture-only":
        return None
    ranges: list[tuple[int, int]] = []
    for part in anchor_str.split(","):
        m = re.match(r"\s*(?:lines\s+)?(\d+)-(\d+|end)\s*$", part)
        if not m:
            return None
        start = int(m.group(1))
        end = brainstorm_lines if m.group(2) == "end" else int(m.group(2))
        ranges.append((start, end))
    return ranges or None


def compute_brainstorm_coverage(
    manifest: dict, brainstorm_text: str, max_depth: int = 2
):
    """`max_depth` defaults to 2 (`#` + `##` headers only)."""
    chapters = [
        (ln, t)
        for ln, t, d in parse_brainstorm_chapters_with_depth(brainstorm_text)
        if d <= max_depth
    ]
    total = len(brainstorm_text.splitlines())
    shared = set(manifest.get("shared_subsections") or [])
    claimers = {t: [] for _, t in chapters}
    orphans = []
    for child in manifest["children"]:
        anchor = parse_anchor(child["brainstorm_anchor"], total)
        if anchor is None:
            orphans.append(
                {
                    "child": child["name"],
                    "anchor": child["brainstorm_anchor"],
                    "error": (
                        "anchor unparseable; expected 'lines X-Y' / 'lines X-end' / "
                        "'lines X-Y, X'-Y'' / 'D4-architecture-only'"
                    ),
                }
            )
            continue
        if any(s > total or e > total for s, e in anchor):
            orphans.append(
                {
                    "child": child["name"],
                    "anchor": child["brainstorm_anchor"],
                    "error": f"anchor out of bounds (brainstorm has {total} lines)",
                }
            )
            continue
        for ln, title in chapters:
            if any(s <= ln <= e for s, e in anchor):
                claimers[title].append(child["name"])
    return {
        "gaps": [t for t, cs in claimers.items() if not cs and t not in shared],
        "orphans": orphans,
    }


# ---------- helpers shared with derive_plan_data.py (kept local; small enough) ----------


def extract_section(text: str, heading_regex: str) -> str:
    """Return markdown content from matching heading until next same-or-shallower heading."""
    out = []
    in_sec = False
    sec_depth = None
    pat = re.compile(heading_regex)
    for line in text.splitlines():
        h = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if h:
            depth = len(h.group(1))
            if pat.search(h.group(2)):
                in_sec = True
                sec_depth = depth
                continue
            if in_sec and depth <= sec_depth:
                break
        if in_sec:
            out.append(line)
    return "\n".join(out)


def parse_markdown_table(section_text: str) -> list[dict]:
    """Parse the first markdown table after a heading; return list of row dicts."""
    rows: list[dict] = []
    header: list[str] | None = None
    for line in section_text.splitlines():
        if not line.strip().startswith("|"):
            if header is not None:
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(c.startswith("-") or c == "" for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


# Cells that mean "unfilled". Width and Clock Domain also reject a bare dash (a wire always
# has a concrete width and a real timing domain).
_BLANK_CELL = {"", "…", "...", "tbd", "todo", "?", "n/a"}
_DASHES = {"-", "–", "—"}


def _is_blank(v: str) -> bool:
    return v.strip().lower() in _BLANK_CELL


def _blank_or_dash(v: str) -> bool:
    return _is_blank(v) or v.strip() in _DASHES


# ---------- frontmatter subset (English canonical anchors) ----------

# Every child .md must declare these frontmatter keys (presence check; empty value is OK).
_REQUIRED_FM_KEYS = (
    "child",
    "parent",
    "brainstorm_anchor",
    "ports",
    "clocks",
    "features",
)


def parse_frontmatter(sub_text: str) -> dict:
    """Parse the YAML front-matter block (``--- ... ---``) at the top of a child
    doc; returns ``{}`` when there is no front-matter block."""
    m = re.match(r"^---\n(.*?)\n---\n", sub_text, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def parse_main_design_tables(main_text: str) -> dict:
    """Extract feature IDs / port names / clock names from main design.md.

    Section headings are English canonical (Surface 1 contract).
    Regex alternations are always grouped via `(...)` to avoid operator
    precedence bugs.
    """
    out = {"features": set(), "ports": set(), "clocks": set()}

    sec = extract_section(main_text, r"§?\s*1\.3.*Feature\s+Table")
    for row in parse_markdown_table(sec):
        fid = row.get("ID", "").strip()
        if fid:
            out["features"].add(fid)

    sec_top = extract_section(main_text, r"§?\s*1\.4\.1.*Top.Level\s+IO")
    top_rows = parse_markdown_table(sec_top)
    if top_rows and "Signal" not in top_rows[0]:
        raise ValueError(
            "design.md §1.4.1 table must use the canonical 'Signal' column "
            f"(found {list(top_rows[0])}); see design-template.md."
        )
    for row in top_rows:
        v = row.get("Signal", "").strip()
        if v:
            out["ports"].add(v)

    sec_inter = extract_section(
        main_text, r"§?\s*1\.4\.2.*Inter.module\s+Interconnects?"
    )
    inter_rows = parse_markdown_table(sec_inter)
    if inter_rows and "Wire" not in inter_rows[0]:
        raise ValueError(
            "design.md §1.4.2 table must use the canonical 'Wire' column "
            f"(found {list(inter_rows[0])}); see design-template.md."
        )
    for row in inter_rows:
        v = row.get("Wire", "").strip()
        if v:
            out["ports"].add(v)

    sec_clk = extract_section(main_text, r"§?\s*1\.6.*Clocks?\s+and\s+Freq")
    clk_rows = parse_markdown_table(sec_clk)
    if clk_rows and "Clock Name" not in clk_rows[0]:
        raise ValueError(
            "design.md §1.6 table must use the canonical 'Clock Name' column "
            f"(found {list(clk_rows[0])}); see design-template.md."
        )
    for row in clk_rows:
        v = row.get("Clock Name", "").strip()
        if v:
            out["clocks"].add(v)

    return out


def compute_frontmatter_subset(
    workdir: Path, manifest: dict, main_design_text: str
) -> dict:
    """Frontmatter `ports / clocks / features` ⊆ main-design tables; all required keys present."""
    main_tables = parse_main_design_tables(main_design_text)
    ports_v: list[dict] = []
    clocks_v: list[dict] = []
    features_v: list[dict] = []
    missing_keys_v: list[dict] = []
    for child in manifest["children"]:
        sub_text = (workdir / child["doc"]).read_text(encoding="utf-8")
        fm = parse_frontmatter(sub_text)
        cname = child["name"]
        missing = [k for k in _REQUIRED_FM_KEYS if k not in fm]
        if missing:
            missing_keys_v.append({"child": cname, "missing": missing})
        for p in fm.get("ports") or []:
            if p not in main_tables["ports"]:
                ports_v.append({"child": cname, "port": p})
        for c in fm.get("clocks") or []:
            cn = c.get("name") if isinstance(c, dict) else c
            if cn and cn not in main_tables["clocks"]:
                clocks_v.append({"child": cname, "clock_name": cn})
        for f in fm.get("features") or []:
            if f not in main_tables["features"]:
                features_v.append({"child": cname, "feature_id": f})
    return {
        "ports_violations": ports_v,
        "clocks_violations": clocks_v,
        "features_violations": features_v,
        "missing_keys": missing_keys_v,
    }


# ---------- self-containment (no by-reference jumps + no cross-child links) ----------

# By-reference-jump patterns (the script owns the set incl. CJK fallbacks; SKILL.md
# prose stays English per the Bilingual Invariant).
# Word boundaries on the ASCII alternatives prevent false positives like "see brainstorming"
# or "see spec D10"; CJK alternatives are left as-is (no word-boundary semantics needed).
_BY_REF_RE = re.compile(
    r"(see\s+brainstorm\b|see\s+spec\s+D\d\b|refer\s+to\s+brainstorm\b|referenced\s+in\s+brainstorm\b"
    r"|见\s*brainstorm|参见\s*brainstorm|见\s*spec\s*D\d|参考\s*brainstorm)",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)")
_LINK_WHITELIST = {"design.md", "child-design-template.md"}


def compute_self_containment(
    workdir: Path, manifest: dict, main_design_text: str
) -> dict:
    """design.md ∪ children must be self-contained: no by-reference jumps to the
    brainstorm (prose pattern or a direct ](brainstorm.md) link), and no <child>.md
    markdown-link to another <child>.md (the cross-child scan is over children only)."""
    child_docs = {child["doc"] for child in manifest["children"]}
    by_ref: list[dict] = []
    cross: list[dict] = []
    docs = [("design.md", main_design_text, False)]
    for child in manifest["children"]:
        docs.append(
            (child["doc"], (workdir / child["doc"]).read_text(encoding="utf-8"), True)
        )
    for name, text, is_child in docs:
        for m in _BY_REF_RE.finditer(text):
            by_ref.append({"file": name, "hit": m.group(0)})
        for lm in _MD_LINK_RE.finditer(text):
            target = lm.group(1).split("/")[-1]
            if target == "brainstorm.md":
                by_ref.append({"file": name, "hit": lm.group(0)})
                continue
            # cross-child link: flagged only when the SOURCE is a child (spec: "in each <child>.md")
            if (
                is_child
                and target not in _LINK_WHITELIST
                and target in child_docs
                and target != name
            ):
                cross.append({"file": name, "link": target})
    return {"by_reference_jumps": by_ref, "cross_child_links": cross}


# ---------- token survival (objective; replaces §3/§4 self-cert) ----------

# Hard-token regex: fenced code blocks, assign/always RTL, sized literals (N'hXX),
# timing (N.N ns), and parameter/localparam numeric definitions — the design
# constants the refmodel/testbench depend on.
#
# TEMP bound (always-body length cap): a prose-embedded, backtick-quoted
# `always @(...)` with no nearby `;` makes the unbounded `[^;]+;` run away to a
# distant semicolon (here L167→L456 = 21KB, L1114→L2066 = 61KB), spanning many
# unrelated sections — an unsatisfiable false-positive token. Real inline RTL
# always-statements terminate within <200 chars; multi-line always blocks live
# inside fenced ```code``` and are captured by the first alternative. Capping the
# body at {1,200} drops only the prose runaways. Revisit: anchor `always` to code
# context instead of a raw length cap.
_HARD_TOKEN_RE = re.compile(
    r"(```[\s\S]*?```"
    r"|assign\s+\w+\s*=[^;]+;"
    r"|always\s*@\([^)]+\)[^;]{1,200};"
    r"|(?:parameter|localparam)\s+(?:\[[^\]]*\]\s*)?\w+\s*=\s*[^;,\n]+"
    r"|\b\d+'[hbdo]\w+"
    r"|\b\d+\.\d+\s*ns)"
)


def compute_token_survival(
    workdir: Path, manifest: dict, brainstorm_text: str, main_design_text: str
) -> dict:
    """Every hard token in the WHOLE brainstorm must appear (substring) in
    design.md ∪ children. Objective + ungameable; guards the verbatim-RTL contract.
    """
    # Read each child body once, not once-per-token.
    child_texts = [
        (workdir / child["doc"]).read_text(encoding="utf-8")
        for child in manifest["children"]
    ]
    haystacks = [main_design_text, *child_texts]
    missing: list[dict] = []
    seen: set[str] = set()
    for tok in _HARD_TOKEN_RE.findall(brainstorm_text):
        if tok in seen:
            continue
        seen.add(tok)
        if not any(tok in h for h in haystacks):
            missing.append({"missing_token": tok[:80]})
    return {"missing_tokens": missing}


# ---------- structural gate (presence, gated columns, freq↔period, clock domain) ----------

# Gated column sets (quality-critical; the rest stay recommended-not-gated).
_GATED_COLS = {
    "1.3": (
        r"§?\s*1\.3.*Feature\s+Table",
        [
            "ID",
            "Feature",
            "Description",
            "Mode/Interface",
            "Priority",
            "HappyPath",
            "CornerCases",
            "NegativeCases",
        ],
    ),
    "1.4.1": (
        r"§?\s*1\.4\.1.*Top.Level\s+IO",
        ["Signal", "Direction", "Clock Domain", "Interface Group", "Role"],
    ),
    "1.5": (
        r"§?\s*1\.5.*Interface\s+Timing\s+Scenarios?",
        ["ScenarioID", "Trigger/Stimulus", "Expected Result", "Timing Constraint"],
    ),
    "1.6": (
        r"§?\s*1\.6.*Clocks?\s+and\s+Freq",
        ["Clock Name", "Nominal Frequency (MHz)", "SDC Period (ns)", "Relationship"],
    ),
}

# §5 Verification-Hints gated columns + the SourceFeature column aliases. The alias set
# mirrors derive_plan_data's source_feature candidates — keep the two in sync so the
# specification gate and the simulation-plan parser can't disagree on the column name.
_HINT_GATED = [
    "CheckID",
    "SourceFeature",
    "ImplementationDetail",
    "Observable",
    "ReferenceRule",
]
_SRC_FEATURE_ALIASES = {"sourcefeature", "source_feature", "sourceid", "featureid"}


def compute_structure(manifest: dict, main_design_text: str, child_texts=None) -> dict:
    presence: list[str] = []
    columns: list[dict] = []
    # §1.4.1 presence is covered by the gated-column loop (adds "§1.4.1 table missing or empty").
    # §1.4.2 must be present as an actual heading (the "(none — N=1)" form is non-empty and passes);
    # a prose cross-reference like "see §1.4.2" must NOT suppress this check.
    if not extract_section(
        main_design_text, r"§?\s*1\.4\.2.*Inter.module\s+Interconnects?"
    ).strip():
        presence.append("§1.4.2 Inter-module Interconnects missing")
    # Gated column presence.
    for sec, (pat, cols) in _GATED_COLS.items():
        rows = parse_markdown_table(extract_section(main_design_text, pat))
        if not rows:
            presence.append(f"§{sec} table missing or empty")
            continue
        header = set(rows[0].keys())
        for c in cols:
            if c not in header:
                columns.append({"section": sec, "missing_column": c})
    # §1.6 period ≈ 1000/freq.
    period_v: list[dict] = []
    clk_rows = parse_markdown_table(
        extract_section(main_design_text, _GATED_COLS["1.6"][0])
    )
    clock_names: set[str] = set()
    for row in clk_rows:
        name = row.get("Clock Name", "").strip()
        if name:
            clock_names.add(name)
        try:
            freq = float(row.get("Nominal Frequency (MHz)", "").strip())
            period = float(row.get("SDC Period (ns)", "").strip())
        except ValueError:
            continue
        if freq > 0 and abs(period - 1000.0 / freq) > 0.01:
            period_v.append({"clock": name, "freq_mhz": freq, "period_ns": period})
    # §1.4.1 Clock Domain values ⊆ §1.6 clock names.
    # Guard: skip when §1.6 is absent (clock_names empty) — the §1.6 absence is already
    # caught by the gated-column loop; running the domain check vacuously would flood the
    # output with spurious violations for every §1.4.1 row.
    domain_v: list[dict] = []
    if clock_names:
        for row in parse_markdown_table(
            extract_section(main_design_text, _GATED_COLS["1.4.1"][0])
        ):
            dom = row.get("Clock Domain", "").strip()
            if dom and dom not in clock_names:
                domain_v.append(
                    {"signal": row.get("Signal", "").strip(), "clock_domain": dom}
                )
    # children ≥ 1 (NOT rtl_modules — already hard-enforced by derive_child_ports).
    manifest_v: list[str] = []
    if len(manifest.get("children") or []) < 1:
        manifest_v.append("manifest.children must have length ≥ 1")
    # Every §1.3 feature ID must be referenced by ≥1 child §5 SourceFeature; child §5
    # gated columns must be present. Coverage is emergent (per-child §5 authored decentrally),
    # so this is a post-wave2 check, not an injection.
    feature_ids = {
        row.get("ID", "").strip()
        for row in parse_markdown_table(
            extract_section(main_design_text, _GATED_COLS["1.3"][0])
        )
        if row.get("ID", "").strip()
    }
    hint_col_v: list[dict] = []
    covered: set[str] = set()
    for cname, body in (child_texts or {}).items():
        sec = extract_section(body, r"§?\s*5\b.*Verification\s+Hints?")
        rows = parse_markdown_table(sec)
        if not rows:
            hint_col_v.append(
                {"child": cname, "error": "§5 Verification Hints table missing"}
            )
            continue
        header = list(rows[0].keys())
        for c in _HINT_GATED:
            if c not in header:
                hint_col_v.append({"child": cname, "missing_column": c})
        src_key = next(
            (h for h in header if h.lower().replace(" ", "") in _SRC_FEATURE_ALIASES),
            None,
        )
        if src_key:
            for row in rows:
                fid = row.get(src_key, "").strip()
                if fid:
                    covered.add(fid)
    # Guard: when child_texts is None, skip the gap check — an empty covered set would
    # otherwise make the set difference MAXIMAL (all features "uncovered"), breaking
    # callers that invoke compute_structure without child bodies.
    feature_gaps = (
        [{"feature_id": fid} for fid in sorted(feature_ids - covered)]
        if child_texts
        else []
    )
    # ----- §1.4.2 interconnect completeness (Width + Clock Domain). A heterogeneous
    # control bundle cannot fill one honest Width row → forced into per-field rows.
    inter_rows = parse_markdown_table(
        extract_section(
            main_design_text, r"§?\s*1\.4\.2.*Inter.module\s+Interconnects?"
        )
    )
    real_rows = [
        r
        for r in inter_rows
        if r.get("Wire", "").strip()
        and not r.get("Wire", "").strip().lower().startswith("(none")
    ]
    interconnect_v: list[dict] = []
    if real_rows:
        header = set(real_rows[0].keys())
        for col in ("Width", "Clock Domain"):
            if col not in header:
                interconnect_v.append({"missing_column": col})
        for row in real_rows:
            wire = row["Wire"].strip()
            if "Width" in header and _blank_or_dash(row.get("Width", "")):
                interconnect_v.append({"wire": wire, "missing_field": "Width"})
            if "Clock Domain" in header:
                dom = row.get("Clock Domain", "").strip()
                if _blank_or_dash(dom):
                    interconnect_v.append(
                        {"wire": wire, "missing_field": "Clock Domain"}
                    )
                elif clock_names and dom not in clock_names:
                    interconnect_v.append(
                        {"wire": wire, "clock_domain": dom, "error": "not in §1.6"}
                    )
    return {
        "presence_violations": presence,
        "column_violations": columns,
        "period_violations": period_v,
        "clock_domain_violations": domain_v,
        "manifest_violations": manifest_v,
        "feature_coverage_gaps": feature_gaps,
        "hint_column_violations": hint_col_v,
        "interconnect_violations": interconnect_v,
    }


# ---------- purity (top-integration child must be pure) ----------


def compute_purity(manifest: dict) -> list:
    """Mirror of validate_rtl_exit.py:49-61: exactly one child covers <TOP>, and that
    child's rtl_modules == [<TOP>] (no bundled logic). <TOP> = manifest['module'].

    `module` is the manifest SSoT top (same source derive_constraints uses as <TOP>);
    fail loud with a clear cause if it is absent rather than misattributing it as miscoverage
    (validate_rtl_exit takes <TOP> from a required CLI arg, which cannot be empty)."""
    top = manifest.get("module")
    if not top:
        return [
            {
                "top": top,
                "error": (
                    "manifest missing required 'module' (top) field — specification "
                    "must set manifest.module to the top RTL module"
                ),
            }
        ]
    children = manifest.get("children", [])
    covering = [c for c in children if top in c.get("rtl_modules", [])]
    if len(covering) != 1:
        return [
            {
                "top": top,
                "covering_count": len(covering),
                "error": (
                    f"top_module {top!r} covered by {len(covering)} children "
                    f"(expected 1) — specification must emit exactly one "
                    f"top-integration child"
                ),
            }
        ]
    if covering[0].get("rtl_modules") != [top]:
        c = covering[0]
        return [
            {
                "child": c.get("name"),
                "rtl_modules": c.get("rtl_modules"),
                "error": (
                    f"top-integration child not pure: expected [{top!r}] only "
                    f"— specification must not bundle logic modules with the "
                    f"top module"
                ),
            }
        ]
    return []


# ---------- main ----------


def main(workdir: str, brainstorm: str) -> int:
    workdir_p = Path(workdir)
    manifest = json.loads((workdir_p / "manifest.json").read_text(encoding="utf-8"))
    brainstorm_text = Path(brainstorm).read_text(encoding="utf-8")
    main_design_text = (workdir_p / "design.md").read_text(encoding="utf-8")

    child_bodies = {
        child["name"]: (workdir_p / child["doc"]).read_text(encoding="utf-8")
        for child in manifest["children"]
    }
    bs_cov = compute_brainstorm_coverage(manifest, brainstorm_text)
    fm_sub = compute_frontmatter_subset(workdir_p, manifest, main_design_text)
    tok = compute_token_survival(workdir_p, manifest, brainstorm_text, main_design_text)
    self_c = compute_self_containment(workdir_p, manifest, main_design_text)
    struct = compute_structure(manifest, main_design_text, child_texts=child_bodies)
    # Fold top-integration purity into the structure sub-block; the existing
    # `or any(struct.values())` in has_fail (below) picks it up — no has_fail change needed.
    struct["purity_violations"] = compute_purity(manifest)

    has_fail = bool(
        bs_cov["gaps"]
        or bs_cov["orphans"]
        or fm_sub["ports_violations"]
        or fm_sub["clocks_violations"]
        or fm_sub["features_violations"]
        or fm_sub["missing_keys"]
        or tok["missing_tokens"]
        or self_c["by_reference_jumps"]
        or self_c["cross_child_links"]
        or any(struct.values())
    )
    coverage = {
        "status": "fail" if has_fail else "pass",
        "brainstorm_coverage": bs_cov,
        "frontmatter_subset": fm_sub,
        "token_survival": tok,
        "self_containment": self_c,
        "structure": struct,
    }
    (workdir_p / "coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if coverage["status"] == "pass" else 1


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="manifest-driven coverage + token-survival verifier "
        "(writes {workdir}/coverage.json; exit 0 pass / 1 fail)."
    )
    ap.add_argument(
        "workdir", help="run workdir containing manifest.json + design.md + children"
    )
    ap.add_argument(
        "--brainstorm",
        required=True,
        help="path to the module-root brainstorm.md (runtime workdir is runs/N/, "
        "so the brainstorm path must be explicit — no parent-dir guess)",
    )
    args = ap.parse_args()
    sys.exit(main(args.workdir, args.brainstorm))
