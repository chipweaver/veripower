#!/usr/bin/env python3
"""derive-ports — deterministic inter-module port derivation.

Given a run workdir with manifest.json (children[].rtl_modules) and interconnects.json,
compute each child's inter-module ports = the wires whose producers or consumers include
one of the child's rtl_modules. This is the FORWARD direction of the wire-attribution
predicate the coverage checker used in reverse — so a child's inter-module ports are
correct-by-construction (specification's main thread injects this into each wave-2 child
prompt; children never hand-guess inter-module ports).

Top-level IO ports are NOT derived here. top-io.json states which child DRIVES each
output, but which inputs a child reads is that child's own implementation decision, made
in wave 2 — a different fact, authored where it is known, and backstopped by
check-coverage's frontmatter-ports subset check.

Usage:  python3 scripts/spec/__main__.py derive-ports --workdir <workdir>
Output: JSON {<child_name>: [<wire>, ...], ...} on stdout (sorted, de-duped).
"""

import json
import sys
from pathlib import Path

from spec.sidecar import load_sidecar, validate_sidecar


def derive_ports(workdir: Path) -> dict:
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    # This verb runs BEFORE the design.md gate and its output is injected into the wave-2
    # child prompts, so a malformed sidecar must stop here rather than silently inject an
    # empty cut-edge list.
    for v in validate_sidecar(workdir, "interconnects.json"):
        sys.exit(
            f"derive-ports: interconnects.json: {v.get('at', '')} {v['error']}".strip()
        )
    wires = load_sidecar(workdir, "interconnects.json")
    children = manifest.get("children")
    if not children:
        sys.exit(
            "derive-ports: manifest.children missing or empty — need >=1 child "
            "(specification Completion Gate)."
        )
    out: dict[str, list[str]] = {}
    for child in children:
        rtl_modules = child.get("rtl_modules")
        if not rtl_modules:
            sys.exit(
                f"derive-ports: child {child.get('name')!r} has no rtl_modules[] — "
                f"required to derive inter-module ports. manifest.children[].rtl_modules is a "
                f"hard requirement (specification Completion Gate)."
            )
        owned = set(rtl_modules)
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
