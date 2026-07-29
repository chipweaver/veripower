#!/usr/bin/env python3
"""check-coverage — manifest-driven coverage + token-survival verifier.

Prints the coverage verdict (JSON) to stdout, containing the `brainstorm_coverage`,
`frontmatter_subset`, and `token_survival` sub-blocks. (The former §3/§4
self-certification `fidelity_coverage` block is removed — those design.md sections
had no downstream consumer and were LLM-self-attested; token-survival replaces them
with an objective whole-brainstorm hard-token check.)

Usage: ``python3 scripts/spec/__main__.py check-coverage --workdir {workdir} --brainstorm <module-root-brainstorm.md>``
Exit: 0 if `status == "pass"`, 1 if `status == "fail"`.
"""

import json
import re
from pathlib import Path

import yaml

from spec.sidecar import load_sidecar, validate_sidecar

# ---------- brainstorm coverage ----------


def parse_brainstorm_chapters_with_depth(brainstorm_text: str):
    """Return list of `(line_no, header_title, depth)` for ATX headers."""
    chapters = []
    for i, line in enumerate(brainstorm_text.splitlines(), start=1):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            chapters.append((i, m.group(2), len(m.group(1))))
    return chapters


def parse_anchor(anchor_str: str, brainstorm_lines: int):
    """Parse anchor; return a list of `(start, end)` ranges, or `None` when unparseable.

    The empty list is distinct from `None`: it means a well-formed anchor that claims no
    brainstorm lines. Caller writes an `orphans` entry only on `None`. Accepted forms:
      * ``lines X-Y``
      * ``lines X-end``
      * ``lines X-Y, X'-Y'`` (comma-separated disjoint ranges)
      * ``D4-architecture-only`` — a child born of the architecture partitioning rather
        than of any one chapter, so it claims nothing and yields the empty list.
    """
    if anchor_str.strip() == "D4-architecture-only":
        return []
    ranges: list[tuple[int, int]] = []
    for part in anchor_str.split(","):
        m = re.match(r"\s*(?:lines\s+)?(\d+)-(\d+|end)\s*$", part)
        if not m:
            return None
        start = int(m.group(1))
        end = brainstorm_lines if m.group(2) == "end" else int(m.group(2))
        ranges.append((start, end))
    return ranges


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
    # Key by (line_no, title): two chapters can share a title, and keying by title alone
    # would let a COVERED same-titled chapter mask a distinct UNCOVERED one.
    claimers = {(ln, t): [] for ln, t in chapters}
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
                claimers[(ln, title)].append(child["name"])
    # Report titles (dedup, order-preserving); a title is a gap iff SOME instance of it is
    # unclaimed and it is not a shared subsection.
    gaps: list[str] = []
    for (ln, title), cs in claimers.items():
        if not cs and title not in shared and title not in gaps:
            gaps.append(title)
    return {"gaps": gaps, "orphans": orphans}


# ---------- frontmatter subset (English canonical anchors) ----------

# Every child .md must declare these frontmatter keys (presence check; empty value is OK).
_BIT_RANGE_RE = re.compile(r"\[(\d+):(\d+)\]$")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_clocks_raw(workdir: Path) -> list[dict]:
    return load_sidecar(workdir, "clocks.json")


def load_clock_names(workdir: Path) -> set[str]:
    return {
        c["name"].strip()
        for c in load_clocks_raw(workdir)
        if isinstance(c.get("name"), str) and c["name"].strip()
    }


def feature_ids_of(workdir: Path) -> set[str]:
    return {
        f["id"].strip()
        for f in load_sidecar(workdir, "features.json")
        if isinstance(f.get("id"), str) and f["id"].strip()
    }


def load_check_hints(workdir: Path, child: str) -> list[dict]:
    return load_sidecar(workdir, f"check-hints/{child}.json")


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


def compute_frontmatter_subset(workdir: Path, manifest: dict) -> dict:
    """Each child's frontmatter `ports / clocks / features` ⊆ the authored sidecars.

    Not a same-fact-twice check: the sidecars are specification's Wave-1 claim about the
    boundary, the frontmatter is the child author's claim about which of it is theirs. Two
    authors, two facts — so a cross-reference that does not resolve is a real defect.
    """
    port_names = {
        p["name"] for p in load_sidecar(workdir, "top-io.json") if p.get("name")
    }
    port_names |= {
        w["wire"] for w in load_sidecar(workdir, "interconnects.json") if w.get("wire")
    }
    clock_names = load_clock_names(workdir)
    feature_ids = feature_ids_of(workdir)
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
            if p not in port_names:
                ports_v.append({"child": cname, "port": p})
        for c in fm.get("clocks") or []:
            cn = c.get("name") if isinstance(c, dict) else c
            if cn and cn not in clock_names:
                clocks_v.append({"child": cname, "clock_name": cn})
        for f in fm.get("features") or []:
            if f not in feature_ids:
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
    # Compare on basenames: link targets are basename-normalized (below), so child_docs
    # and the source name must be too — else a directory-prefixed child["doc"]
    # (e.g. "sub/b.md") would never match a `](b.md)` link and cross-child links slip through.
    child_docs = {Path(child["doc"]).name for child in manifest["children"]}
    by_ref: list[dict] = []
    cross: list[dict] = []
    docs = [("design.md", main_design_text, False)]
    for child in manifest["children"]:
        docs.append(
            (child["doc"], (workdir / child["doc"]).read_text(encoding="utf-8"), True)
        )
    # A by-reference jump is the same defect wherever it is written, hints included.
    for hp in sorted((workdir / "check-hints").glob("*.json")):
        docs.append((f"check-hints/{hp.name}", hp.read_text(encoding="utf-8"), False))
    for name, text, is_child in docs:
        name_base = Path(name).name
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
                and target != name_base
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


def _strip_ppa_targets_section(brainstorm_text: str) -> str:
    """Remove the brainstorm's `PPA Targets` chapter (checklist Section Layout, D6)
    before hard-token extraction. PPA numbers legitimately live ONLY in ppa.json (the
    design-template §1.1 single-home rule), so a D6-only token like `0.5 ns` must not
    demand prose survival in design.md ∪ children — that demand and the single-home
    rule would otherwise deadlock the Step-6 loop. A token that ALSO appears outside
    the PPA chapter is still extracted from its other occurrence and must survive."""
    out: list[str] = []
    skipping, skip_depth = False, 0
    for line in brainstorm_text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            depth = len(m.group(1))
            if skipping and depth <= skip_depth:
                skipping = False
            if not skipping and re.search(r"PPA\s+Targets", m.group(2), re.IGNORECASE):
                skipping, skip_depth = True, depth
                continue
        if not skipping:
            out.append(line)
    return "\n".join(out)


def compute_token_survival(
    workdir: Path, manifest: dict, brainstorm_text: str, main_design_text: str
) -> dict:
    """Every hard token in the WHOLE brainstorm — minus the `PPA Targets` chapter
    (see _strip_ppa_targets_section: its numerics single-home in ppa.json) — must
    appear (substring) in design.md ∪ children. Objective + ungameable; guards the
    verbatim-RTL contract.
    """
    brainstorm_text = _strip_ppa_targets_section(brainstorm_text)
    # Read each child body once, not once-per-token. check-hints/<child>.json is part of the
    # haystack: implementation_detail_verbatim is where brainstorm RTL formulas land, and
    # survival is about the information, not the file format holding it.
    child_texts = [
        (workdir / child["doc"]).read_text(encoding="utf-8")
        for child in manifest["children"]
    ]
    hint_texts = [
        p.read_text(encoding="utf-8")
        for p in sorted((workdir / "check-hints").glob("*.json"))
    ]
    haystacks = [main_design_text, *child_texts, *hint_texts]
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


def compute_structure(
    workdir: Path, manifest: dict, main_design_text: str, child_texts=None
) -> dict:
    """Cross-file and cross-field checks the sidecar schemas cannot express.

    Everything about one sidecar's own shape — required fields, types, enums, and the two
    conditional requirements on top-io (an output declares owner; a reset row declares
    polarity and kind) — is validated by the schemas below and not restated here.
    """
    clock_names = load_clock_names(workdir)
    ports = load_sidecar(workdir, "top-io.json")
    wires = load_sidecar(workdir, "interconnects.json")

    # period_ns ≈ 1000/freq_mhz. A cross-field arithmetic relation, so not expressible in
    # JSON Schema; both operands are hand-authored, so the check carries real information.
    period_v: list[dict] = []
    for c in load_clocks_raw(workdir):
        if not isinstance(c, dict):
            continue
        freq, period = c.get("freq_mhz"), c.get("period_ns")
        if not _is_number(freq) or not _is_number(period):
            continue  # a type defect is derive-constraints' schema report, not ours
        if freq > 0 and abs(period - 1000.0 / freq) > 0.01:
            period_v.append(
                {"clock": c.get("name"), "freq_mhz": freq, "period_ns": period}
            )

    # clock_domain ⊆ clocks.json names, on both sidecars. Skip when there are no names:
    # running it vacuously would flag every port.
    domain_v: list[dict] = []
    interconnect_v: list[dict] = []
    if clock_names:
        for e in ports:
            dom = e.get("clock_domain")
            if dom and dom not in clock_names:
                domain_v.append({"signal": e.get("name"), "clock_domain": dom})
        for w in wires:
            dom = w.get("clock_domain")
            if dom and dom not in clock_names:
                interconnect_v.append(
                    {
                        "wire": w.get("wire"),
                        "clock_domain": dom,
                        "error": "not in clocks.json",
                    }
                )

    # width vs the [h:l] range a name carries. An [i] index (a register-file element) makes
    # no width claim and is skipped.
    width_v: list[dict] = []
    for e in ports + wires:
        n, w = e.get("name") or e.get("wire"), e.get("width")
        if not isinstance(n, str) or not isinstance(w, int):
            continue
        m = _BIT_RANGE_RE.search(n)
        if m:
            implied = int(m.group(1)) - int(m.group(2)) + 1
            if implied != w:
                width_v.append({"name": n, "width": w, "name_implies": implied})

    # children ≥ 1 (NOT rtl_modules — already hard-enforced by derive_ports).
    manifest_v: list[str] = []
    if len(manifest.get("children") or []) < 1:
        manifest_v.append("manifest.children must have length ≥ 1")

    # Every features.json id must be referenced by ≥1 check hint. Coverage is emergent
    # (hints authored decentrally per child), so this is a post-wave2 check.
    feature_ids = feature_ids_of(workdir)
    hint_col_v: list[dict] = []
    covered: set[str] = set()
    for cname in child_texts or {}:
        for v in validate_sidecar(
            workdir, f"check-hints/{cname}.json", schema="check-hints.schema.json"
        ):
            hint_col_v.append({"child": cname, **v})
        for hint in load_check_hints(workdir, cname):
            fid = hint.get("source_feature")
            if isinstance(fid, str) and fid.strip():
                covered.add(fid.strip())
    # Guard: when child_texts is None, skip the gap check — an empty covered set would
    # otherwise make the set difference MAXIMAL (all features "uncovered").
    feature_gaps = (
        [{"feature_id": fid} for fid in sorted(feature_ids - covered)]
        if child_texts
        else []
    )

    # An output's owner must be a manifest child that lists the port in its frontmatter.
    # Presence of owner is the schema's; resolving it against the manifest and the child's
    # own declaration is cross-file. Owner DECLARES the driver rather than being inferred
    # from claimer counts, which cannot tell a top mux of N leaf sources from N leaves
    # conflicting. The top-integration child as owner passes; the leaf-owner preference is
    # documented guidance, not a deterministic block.
    top_io_driver_v: list[dict] = []
    if child_texts:
        child_names = {c["name"] for c in manifest.get("children", [])}
        child_ports = {
            cname: set(parse_frontmatter(body).get("ports") or [])
            for cname, body in child_texts.items()
        }
        for e in ports:
            if e.get("direction") != "output":
                continue
            sig, owner = e.get("name"), e.get("owner")
            if not owner:
                continue  # schema reports the absence
            if owner not in child_names:
                top_io_driver_v.append(
                    {
                        "signal": sig,
                        "owner": owner,
                        "error": "owner is not a manifest child",
                    }
                )
            elif sig not in child_ports.get(owner, set()):
                top_io_driver_v.append(
                    {
                        "signal": sig,
                        "owner": owner,
                        "error": "owner child does not list this port in its ports "
                        "(declared driver does not drive it)",
                    }
                )

    return {
        "features_schema_violations": validate_sidecar(workdir, "features.json"),
        "timing_scenarios_schema_violations": validate_sidecar(
            workdir, "timing-scenarios.json"
        ),
        "top_io_schema_violations": validate_sidecar(workdir, "top-io.json"),
        "interconnects_schema_violations": validate_sidecar(
            workdir, "interconnects.json"
        ),
        "period_violations": period_v,
        "clock_domain_violations": domain_v,
        "width_violations": width_v,
        "manifest_violations": manifest_v,
        "feature_coverage_gaps": feature_gaps,
        "hint_column_violations": hint_col_v,
        "interconnect_violations": interconnect_v,
        "top_io_driver_violations": top_io_driver_v,
    }


def compute_purity(manifest: dict) -> list:
    """Mirror of the rtl check-partition gate (rtl/partition.py): exactly one child covers <TOP>, and that
    child's rtl_modules == [<TOP>] (no bundled logic). <TOP> = manifest['module'].

    `module` is the manifest SSoT top (same source derive_constraints uses as <TOP>);
    fail loud with a clear cause if it is absent rather than misattributing it as miscoverage
    (the rtl check-partition verb takes <TOP> from a required CLI arg, which cannot be empty)."""
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


def run(workdir: str, brainstorm: str) -> int:
    workdir_p = Path(workdir)
    manifest = json.loads((workdir_p / "manifest.json").read_text(encoding="utf-8"))
    # Normalize a missing/empty children list once, so a manifest without 'children'
    # yields the graceful `manifest.children must have length ≥ 1` verdict rather than a
    # KeyError traceback from the downstream `manifest["children"]` accesses.
    manifest["children"] = manifest.get("children") or []
    brainstorm_text = Path(brainstorm).read_text(encoding="utf-8")
    main_design_text = (workdir_p / "design.md").read_text(encoding="utf-8")

    child_bodies = {
        child["name"]: (workdir_p / child["doc"]).read_text(encoding="utf-8")
        for child in manifest["children"]
    }
    bs_cov = compute_brainstorm_coverage(manifest, brainstorm_text)
    fm_sub = compute_frontmatter_subset(workdir_p, manifest)
    tok = compute_token_survival(workdir_p, manifest, brainstorm_text, main_design_text)
    self_c = compute_self_containment(workdir_p, manifest, main_design_text)
    struct = compute_structure(
        workdir_p, manifest, main_design_text, child_texts=child_bodies
    )
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
    print(json.dumps(coverage, ensure_ascii=False, indent=2))
    return 0 if coverage["status"] == "pass" else 1
