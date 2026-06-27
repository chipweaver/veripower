#!/usr/bin/env python3
"""rtl check-conformance — spec↔RTL presence-level checks (Tier 2).

Emits a one-line JSON verdict on stdout the main thread reads:
  {"status": "pass|fail", "violations": [...], "fail_reason"?: str}
Status truth = exit code (0 pass / 1 fail). Presence-level identifier scan only
(NOT elaboration — that is lint-cdc's job via SpyGlass). Each violation names a
`child` so the main thread's bounded self-converge loop can re-dispatch it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rtl._ledger import LedgerError, load_ledger


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _strip_comments(text: str) -> str:
    """MASK string literals first, then remove /* */ block + // line comments — so presence checks
    aren't fooled by commented-out decls, AND a string-embedded `/*`/`*/` can't swallow real code
    between two string literals. `ifdef`-gated / macro-expanded code remains a documented
    presence-level ceiling."""
    text = re.sub(
        r'"(?:\\.|[^"\\\n])*"', " ", text
    )  # mask SV string literals (no newline span)
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)  # block comments
    return re.sub(r"//[^\n]*", " ", text)  # line comments


def _child_text(workdir: Path, rec: dict) -> str:
    """Concatenate a child's RTL files, comments stripped (missing file skipped —
    surfaces as a module-presence violation, not a crash)."""
    blobs = []
    for f in rec.get("files", []):
        p = workdir / f
        if p.exists():
            blobs.append(p.read_text(encoding="utf-8", errors="replace"))
    return _strip_comments("\n".join(blobs))


def _module_names(text: str) -> set:
    """Verilog-2001 module declarations: `module <name>`."""
    return set(re.findall(r"(?m)^\s*module\s+([A-Za-z_]\w*)", text))


def _has_token(text: str, name: str) -> bool:
    """Whole-word presence of an identifier (presence proxy)."""
    return (
        re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", text)
        is not None
    )


def check_annotation_reality(workdir, ledger) -> list:
    """Child-reported RTL-true annotation names must exist in that child's RTL.
    sgdc.sync_cell / reset_synchronizer are module names ('-name must match the netlist').
    sdc.create_generated_clock[].module is the child-authored clock-gen module (RTL-true,
    same reporting child — the derive-constraints verb only emits a deferred `#` placeholder, so the
    child annotation is the SOLE source and synthesis has no backstop). text is comment-stripped
    upstream by _child_text. .pin is NOT checked (pin presence is too fragile)."""
    v = []
    for name, rec in ledger.items():
        text = _child_text(workdir, rec)
        ann = rec.get("annotations", {}) or {}
        sgdc = ann.get("sgdc", {}) or {}
        for kind in ("sync_cell", "reset_synchronizer"):
            for mod in sgdc.get(kind) or []:
                # _has_token = presence proxy (instantiation counts; a lib cell need not be declared here)
                if not _has_token(text, mod):
                    v.append(
                        {
                            "child": name,
                            "kind": "annotation_reality",
                            "annotation": kind,
                            "name": mod,
                        }
                    )
        sdc = ann.get("sdc", {}) or {}
        for entry in sdc.get("create_generated_clock") or []:
            mod = entry.get("module") if isinstance(entry, dict) else None
            if mod and not _has_token(text, mod):
                v.append(
                    {
                        "child": name,
                        "kind": "annotation_reality",
                        "annotation": "create_generated_clock",
                        "name": mod,
                    }
                )
    return v


# ---- minimal design.md §1.4.2 parse (mirrors check-coverage canonical-column contract) ----


def _extract_section(text: str, heading_regex: str) -> str:
    out, in_sec, depth = [], False, None
    pat = re.compile(heading_regex)
    for line in text.splitlines():
        h = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if h:
            d = len(h.group(1))
            if pat.search(h.group(2)):
                in_sec, depth = True, d
                continue
            if in_sec and d <= depth:
                break
        if in_sec:
            out.append(line)
    return "\n".join(out)


def _table_rows(section_text: str) -> list:
    rows, header = [], None
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


def _interconnect_wires(design_text: str) -> list:
    """§1.4.2 Wire names, skipping the canonical N=1 placeholder row
    ('(none — N=1 ...)') so a legitimately empty interconnect isn't flagged a phantom wire."""
    sec = _extract_section(design_text, r"§?\s*1\.4\.2.*Inter.module\s+Interconnects?")
    out = []
    for r in _table_rows(sec):
        w = r.get("Wire", "").strip()
        if w and not w.lower().startswith("(none") and "n=1" not in w.lower():
            out.append(w)
    return out


def check_top_integration(workdir, manifest, top, ledger, design_text) -> list:
    """In the top-integration child's RTL, every non-top rtl_module name and every §1.4.2
    Wire name must appear as a token (presence proxy for instantiation / net use)."""
    v = []
    topc = next(
        (c for c in manifest["children"] if top in c.get("rtl_modules", [])), None
    )
    if topc is None:
        return v  # coverage failure already caught by the exit gate (partition)
    rec = ledger.get(topc["name"])
    if rec is None:
        return v
    text = _child_text(workdir, rec)
    non_top = {
        m for c in manifest["children"] for m in c.get("rtl_modules", []) if m != top
    }
    owner_of = {
        m: c["name"] for c in manifest["children"] for m in c.get("rtl_modules", [])
    }
    for mod in sorted(non_top):
        if not _has_token(text, mod):
            # child = topc (top owns instantiation); owner_child = the sibling that authored mod,
            # so the C-loop re-dispatch set can include the real fix locus when a sibling renamed it.
            v.append(
                {
                    "child": topc["name"],
                    "kind": "top_instantiation",
                    "missing_module": mod,
                    "owner_child": owner_of.get(mod),
                }
            )
    for wire in _interconnect_wires(design_text):
        if not _has_token(text, wire):
            v.append(
                {
                    "child": topc["name"],
                    "kind": "interconnect_wire",
                    "missing_wire": wire,
                }
            )
    return v


def check_module_presence(workdir, manifest, ledger) -> list:
    v = []
    for child in manifest["children"]:
        name = child["name"]
        rec = ledger.get(name)
        if rec is None:
            continue  # blocked/absent child is the exit gate's (partition) job, not here
        decl = _module_names(_child_text(workdir, rec))
        for mod in child.get("rtl_modules", []):
            if mod not in decl:
                v.append(
                    {"child": name, "kind": "module_presence", "missing_module": mod}
                )
    return v


def run(workdir, manifest, top, ledger, design) -> int:
    workdir, manifest, ledger, design = (
        Path(workdir),
        Path(manifest),
        Path(ledger),
        Path(design),
    )
    try:
        manifest_data = _read_json(manifest)
        ledger_data = load_ledger(ledger)
        design_text = design.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError, LedgerError) as e:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "violations": [],
                    "fail_reason": f"conformance precheck unreadable: {e}",
                },
                ensure_ascii=False,
            )
        )
        return 1

    violations = (
        check_module_presence(workdir, manifest_data, ledger_data)
        + check_annotation_reality(workdir, ledger_data)
        + check_top_integration(workdir, manifest_data, top, ledger_data, design_text)
    )

    verdict = {"status": "pass" if not violations else "fail", "violations": violations}
    if violations:
        children = sorted({x["child"] for x in violations})
        verdict["fail_reason"] = (
            "conformance: spec↔RTL presence violations in " + ", ".join(children)
        )
    print(json.dumps(verdict, ensure_ascii=False))
    return 0 if not violations else 1
