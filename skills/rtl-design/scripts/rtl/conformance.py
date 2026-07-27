#!/usr/bin/env python3
"""rtl check-conformance — spec↔RTL presence-level checks + strict Verilog-2001 dialect gate.

Emits a one-line JSON verdict on stdout the main thread reads:
  {"status": "pass|fail", "violations": [...], "fail_reason"?: str}
Status truth = exit code (0 pass / 1 fail). Presence-level identifier scan only
(NOT elaboration — that is lint-cdc's job via SpyGlass); the dialect gate is likewise a
presence-level scan (file extension + SystemVerilog-only keywords), not elaboration. Each
violation names a `child` so the main thread's self-converge loop can re-dispatch it.
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


def _uses(text: str, mod: str) -> bool:
    """`mod` is referenced beyond its own `module mod` declaration in `text` — an instantiation
    proxy for the reachability check (orphan-safe: a module that is only *declared* in a child file,
    never instantiated, does not count as used). Whole-word boundaries match `_has_token`."""
    esc = re.escape(mod)
    tokens = re.findall(r"(?<![A-Za-z0-9_])" + esc + r"(?![A-Za-z0-9_])", text)
    decls = re.findall(r"(?m)^\s*module\s+" + esc + r"(?![A-Za-z0-9_])", text)
    return len(tokens) > len(decls)


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


_PIPE = re.compile(r"(?<!\\)\|")


def _split_row(line: str) -> list:
    """Split a Markdown table row on UNescaped '|' (a literal pipe in a cell is
    written '\\|'); unescape '\\|' -> '|' and trim each cell. Without honoring the
    escape, a cell quoting a pipe over-splits and every column after it shifts right."""
    parts = _PIPE.split(line.strip())
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return [p.replace("\\|", "|").strip() for p in parts]


def _table_rows(section_text: str) -> list:
    rows, header = [], None
    for line in section_text.splitlines():
        if not line.strip().startswith("|"):
            if header is not None:
                break
            continue
        cells = _split_row(line)
        if header is None:
            header = cells
            continue
        if all(c.startswith("-") or c == "" for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def _interconnect_wires(design_text: str) -> list:
    """§1.4.2 Wire names, skipping the canonical N=1 placeholder row
    ('(none — N=1 ...)') so a legitimately empty interconnect isn't flagged a phantom wire.

    The `(none` test is the whole rule, matching specification's check-coverage, which
    partitions the same rows to decide which ones it validates Width / Clock Domain on.
    Any looser test here exempts a row specification validated as a real wire, dropping it
    from the top-integration check with nothing to say so."""
    sec = _extract_section(design_text, r"§?\s*1\.4\.2.*Inter.module\s+Interconnects?")
    out = []
    for r in _table_rows(sec):
        w = r.get("Wire", "").strip()
        if w and not w.lower().startswith("(none"):
            out.append(w)
    return out


def check_top_integration(workdir, manifest, top, ledger, design_text) -> list:
    """Every non-top rtl_module must be INTEGRATED — reachable from the top module through the
    instantiation hierarchy (presence proxy), not merely instantiated by the top file directly.
    This accepts legitimate hierarchical designs (a shared primitive nested inside a functional
    unit that the top instantiates: top -> unit -> primitive) while still catching truly-orphaned
    or renamed modules. Every §1.4.2 Wire name must still appear as a token in the top-integration
    child's RTL (the top owns the interconnect)."""
    v = []
    topc = next(
        (c for c in manifest["children"] if top in c.get("rtl_modules", [])), None
    )
    if topc is None:
        return v  # coverage failure already caught by the exit gate (partition)
    rec = ledger.get(topc["name"])
    if rec is None:
        return v
    owner_of = {
        m: c["name"] for c in manifest["children"] for m in c.get("rtl_modules", [])
    }
    all_mods = set(owner_of)
    # Per-child comment-stripped RTL; a reachable module "uses" every module-name token present in
    # its OWNER child's RTL. Reachability BFS from `top` over this use-graph integrates nested
    # submodules (top -> functional unit -> primitive) without requiring flat top-level
    # instantiation. A module unreachable from `top` is genuinely orphaned (or renamed → its
    # manifest name appears nowhere), which is the real defect this check exists to catch.
    child_text = {}
    for c in manifest["children"]:
        crec = ledger.get(c["name"])
        child_text[c["name"]] = _child_text(workdir, crec) if crec else ""
    text = child_text[
        topc["name"]
    ]  # top-integration child RTL (for the §1.4.2 wire check)
    reachable, frontier = set(), [top]
    while frontier:
        mod = frontier.pop()
        if mod in reachable:
            continue
        reachable.add(mod)
        ctext = child_text.get(owner_of.get(mod), "")
        for cand in all_mods:
            if cand not in reachable and _uses(ctext, cand):
                frontier.append(cand)
    for mod in sorted(all_mods):
        if mod != top and mod not in reachable:
            # child = topc (integration is the top-integration child's responsibility); owner_child
            # = the sibling that authored mod, so the C-loop re-dispatch set can reach the real fix
            # locus (e.g. when a sibling renamed it so its manifest name resolves nowhere).
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


# SystemVerilog-only reserved words that are NOT legal Verilog-2001 — a synthesizable-RTL
# subset (SVA / class / TB-only constructs are omitted: this gate sees only DUT RTL from the
# ledger, never the testbench). coding-rules already forbids using any reserved word as an
# identifier, so a whole-word hit (comments/strings masked) is a genuine SV construct, not a
# collision with a legitimately-named V2001 signal.
_SV_ONLY_KEYWORDS = (
    "logic",
    "bit",
    "byte",
    "shortint",
    "int",
    "longint",
    "packed",
    "always_ff",
    "always_comb",
    "always_latch",
    "typedef",
    "enum",
    "struct",
    "union",
    "interface",
    "endinterface",
    "modport",
    "package",
    "endpackage",
    "program",
    "endprogram",
    "class",
    "endclass",
    "import",
    "export",
    "unique",
    "priority",
)


def check_dialect(workdir, ledger) -> list:
    """Strict Verilog-2001 producer gate (rtl-design only). Every child RTL source in the ledger
    must be a `.v` file (or `.vh` header) — NOT `.sv`/`.svh` — and carry no SystemVerilog-only
    construct. Rationale: the kernel's downstream `rtl` selectors match `*.v` ALONE, so a `.sv`
    artifact silently drops out of the derived dependency graph (it did — the run-1 pipeline
    deadlock), and coding-rules mandates V2001. Scans the ledger's OWN files only, so the sim TB
    `.sv` is never in scope; non-HDL support files (.mem/.h/…) are ignored. Comment/string content
    is masked (shared `_strip_comments`), so a `logic` inside a comment is not a violation. A
    violation names its `child`, so 4.3's self-converge loop re-dispatches that child to fix it."""
    v = []
    for name, rec in ledger.items():
        for f in rec.get("files", []):
            suffix = Path(f).suffix.lower()
            if suffix in (".sv", ".svh"):
                v.append(
                    {
                        "child": name,
                        "kind": "dialect",
                        "file": f,
                        "reason": f"SystemVerilog file extension '{suffix}' — RTL must be Verilog-2001 (.v / .vh)",
                    }
                )
                continue  # extension already disqualifies; skip the token scan
            if suffix not in (".v", ".vh"):
                continue  # non-HDL support file (.mem/.h/…) — out of the dialect gate's scope
            p = workdir / f
            if not p.exists():
                continue  # a missing file surfaces as a module_presence violation, not here
            text = _strip_comments(p.read_text(encoding="utf-8", errors="replace"))
            for kw in _SV_ONLY_KEYWORDS:
                if _has_token(text, kw):
                    v.append(
                        {
                            "child": name,
                            "kind": "dialect",
                            "file": f,
                            "sv_construct": kw,
                            "reason": f"SystemVerilog-only construct '{kw}' — RTL must be Verilog-2001",
                        }
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
        + check_dialect(workdir, ledger_data)
    )

    verdict = {"status": "pass" if not violations else "fail", "violations": violations}
    if violations:
        children = sorted({x["child"] for x in violations})
        verdict["fail_reason"] = (
            "conformance: spec↔RTL presence violations in " + ", ".join(children)
        )
    print(json.dumps(verdict, ensure_ascii=False))
    return 0 if not violations else 1
