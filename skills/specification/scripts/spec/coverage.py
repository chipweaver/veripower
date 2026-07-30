#!/usr/bin/env python3
"""check-coverage — the deterministic cross-file gate for the specification stage.

Prints the verdict (JSON) to stdout with the `frontmatter_subset` and `structure` sub-blocks.

Everything here is a set operation over identifiers that already exist for a downstream
consumer: a name resolves against the sidecar that owns it, or an id appears on both sides of
a join. That is the whole remit. Anything needing a reference frame — does this doc realize
the brainstorm, is this encoding adequate — is a reader's job, not a script's, and belongs to
the spec-review lenses.

Usage: ``python3 scripts/spec/__main__.py check-coverage --workdir {workdir}``
Exit: 0 if `status == "pass"`, 1 if `status == "fail"`.
"""

import json
import re
from pathlib import Path

import yaml

from spec.sidecar import load_sidecar, validate_sidecar

# ---------- frontmatter subset (English canonical anchors) ----------

# Every child .md must declare these frontmatter keys (presence check; empty value is OK).
_BIT_RANGE_RE = re.compile(r"\[(\d+):(\d+)\]$")


def load_clock_names(workdir: Path) -> set[str]:
    return {
        c["name"].strip()
        for c in load_sidecar(workdir, "clocks.json")
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


_REQUIRED_FM_KEYS = ("ports", "clocks", "features")


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


# ---------- structural gate (presence, gated fields, freq↔period, clock domain) ----------


def compute_structure(workdir: Path, manifest: dict, child_texts: dict) -> dict:
    """Cross-file and cross-field checks the sidecar schemas cannot express.

    Everything about one sidecar's own shape — required fields, types, enums, and the
    conditional requirement on a top-io reset row (it declares polarity and kind) — is
    validated by the schemas below and not restated here.
    """
    clock_names = load_clock_names(workdir)
    ports = load_sidecar(workdir, "top-io.json")
    wires = load_sidecar(workdir, "interconnects.json")

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

    # Every features.json id must be referenced by ≥1 check hint. Coverage is emergent
    # (hints authored decentrally per child), so this is a post-wave2 check.
    feature_ids = feature_ids_of(workdir)
    hint_col_v: list[dict] = []
    covered: set[str] = set()
    for cname in child_texts:
        for v in validate_sidecar(
            workdir, f"check-hints/{cname}.json", schema="check-hints.schema.json"
        ):
            hint_col_v.append({"child": cname, **v})
        for hint in load_check_hints(workdir, cname):
            fid = hint.get("source_feature")
            if isinstance(fid, str) and fid.strip():
                covered.add(fid.strip())
    feature_gaps = [{"feature_id": fid} for fid in sorted(feature_ids - covered)]

    # Every top-level output is claimed by some child's frontmatter ports. An output no child
    # lists is one nothing drives — a defect no single child's author can see, since each of
    # them knows only their own claim. WHICH child drives it, when several claim it, is not
    # asked: a top mux of N leaf sources and N leaves conflicting are indistinguishable from
    # the claims alone, and only a reader of the bodies can tell them apart.
    top_io_driver_v: list[dict] = []
    claimed: set[str] = set()
    for body in child_texts.values():
        claimed |= set(parse_frontmatter(body).get("ports") or [])
    for e in ports:
        if e.get("direction") != "output":
            continue
        sig = e.get("name")
        if sig and sig not in claimed:
            top_io_driver_v.append(
                {
                    "signal": sig,
                    "error": "no child lists this output in its frontmatter ports "
                    "(nothing drives it)",
                }
            )

    return {
        "features_schema_violations": validate_sidecar(workdir, "features.json"),
        "top_io_schema_violations": validate_sidecar(workdir, "top-io.json"),
        "interconnects_schema_violations": validate_sidecar(
            workdir, "interconnects.json"
        ),
        "clock_domain_violations": domain_v,
        "width_violations": width_v,
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


def verdict(workdir) -> dict:
    """The gate verdict as data (no printing, no exit). finalize re-runs this in-process as
    the divergence-proof invariant: every check here is a set operation over the workdir's
    own files, so a clean Step-5 verdict stays true unless someone edited a sidecar or a
    child doc afterwards."""
    workdir_p = Path(workdir)
    manifest = json.loads((workdir_p / "manifest.json").read_text(encoding="utf-8"))
    child_bodies = {
        child["name"]: (workdir_p / child["doc"]).read_text(encoding="utf-8")
        for child in manifest["children"]
    }
    fm_sub = compute_frontmatter_subset(workdir_p, manifest)
    struct = compute_structure(workdir_p, manifest, child_texts=child_bodies)
    # Fold top-integration purity into the structure sub-block; the existing
    # `or any(struct.values())` in has_fail (below) picks it up — no has_fail change needed.
    struct["purity_violations"] = compute_purity(manifest)

    has_fail = bool(
        fm_sub["ports_violations"]
        or fm_sub["clocks_violations"]
        or fm_sub["features_violations"]
        or fm_sub["missing_keys"]
        or any(struct.values())
    )
    return {
        "status": "fail" if has_fail else "pass",
        "frontmatter_subset": fm_sub,
        "structure": struct,
    }


def violated_keys(cov: dict) -> list[str]:
    """The names of the non-empty violation lists in a verdict — what a caller reports when
    it has no room for the whole document."""
    out = [k for k, v in cov.get("frontmatter_subset", {}).items() if v]
    out += [k for k, v in cov.get("structure", {}).items() if v]
    return out


def run(workdir: str) -> int:
    cov = verdict(workdir)
    print(json.dumps(cov, ensure_ascii=False, indent=2))
    return 0 if cov["status"] == "pass" else 1
