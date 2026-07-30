#!/usr/bin/env python3
"""derive-ports — deterministic inter-module port derivation.

Given a run workdir with manifest.json (children[].rtl_modules) and interconnects.json,
compute each child's inter-module ports = the wires whose producers or consumers include
one of the child's rtl_modules. This is the FORWARD direction of the wire-attribution
predicate the coverage checker used in reverse — so a child's inter-module ports are
correct-by-construction (specification's main thread injects this into each wave-2 child
prompt; children never hand-guess inter-module ports).

Top-level IO ports are NOT derived here. Which top-IO ports a child drives or reads is that
child's own implementation decision, made in wave 2 and declared in its frontmatter — a
different fact, authored where it is known, and backstopped by check-crossrefs.

This verb also decides the top-partition purity rule, because it is the cheapest moment to
decide it: the partition gate is next, so a violation is caught before N children are written
against it. rtl-design's check-partition re-decides the same rule at its own entry;
`tests/contracts/test_partition_purity_agreement.py` locks the two together.

Usage:  python3 scripts/spec/__main__.py derive-ports --workdir <workdir>
Output: JSON {<child_name>: [<wire>, ...], ...} on stdout (sorted, de-duped).
"""

import json
import sys
from pathlib import Path

from spec.sidecar import SidecarError, read_sidecar


def check_purity(manifest: dict) -> list:
    """Exactly one child covers <TOP>, and that child's rtl_modules == [<TOP>] (no bundled
    logic). <TOP> = manifest['module'] — the same source derive_constraints pins; fail loud
    with a clear cause if it is absent rather than misattributing it as miscoverage (the rtl
    check-partition verb takes <TOP> from a required CLI arg, which cannot be empty)."""
    top = manifest.get("module")
    if not top:
        return [
            "manifest missing required 'module' (top) — specification must set "
            "manifest.module to the top RTL module"
        ]
    covering = [
        c for c in manifest.get("children", []) if top in c.get("rtl_modules", [])
    ]
    if len(covering) != 1:
        return [
            f"top_module {top!r} covered by {len(covering)} children (expected 1) — "
            f"specification must emit exactly one top-integration child"
        ]
    if covering[0].get("rtl_modules") != [top]:
        return [
            f"top-integration child {covering[0].get('name')!r} not pure: rtl_modules is "
            f"{covering[0].get('rtl_modules')}, expected [{top!r}] only — do not bundle "
            f"logic modules with the top module"
        ]
    return []


def derive_ports(workdir: Path) -> dict:
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    # This verb runs BEFORE the partition gate and its output is injected into the wave-2
    # child prompts, so a malformed sidecar must stop here rather than silently inject an
    # empty cut-edge list.
    try:
        wires = read_sidecar(workdir, "interconnects.json")
    except SidecarError as exc:
        sys.exit(f"derive-ports: {exc}")
    children = manifest.get("children")
    if not children:
        sys.exit(
            "derive-ports: manifest.children missing or empty — need >=1 child "
            "(specification Completion Gate)."
        )
    for child in children:
        if not child.get("rtl_modules"):
            sys.exit(
                f"derive-ports: child {child.get('name')!r} has no rtl_modules[] — "
                f"required to derive inter-module ports. manifest.children[].rtl_modules is a "
                f"hard requirement (specification Completion Gate)."
            )
    # Purity reads rtl_modules, so it runs after the loop above has proved every child has it.
    for v in check_purity(manifest):
        sys.exit(f"derive-ports: {v}")
    out: dict[str, list[str]] = {}
    for child in children:
        owned = set(child["rtl_modules"])
        out[child["name"]] = sorted(
            {
                w["wire"]
                for w in wires
                if w.get("wire")
                and owned
                & (set(w.get("producers") or []) | set(w.get("consumers") or []))
            }
        )
    return out
