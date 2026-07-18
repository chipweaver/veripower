#!/usr/bin/env python3
"""derive-ports — deterministic inter-module port derivation.

Given a run workdir with manifest.json (children[].rtl_modules) and design.md
(§1.4.2 Inter-module Interconnects wire table), compute each child's inter-module
ports = the set of §1.4.2 wires whose Producer or Consumer RTL module is one of the
child's rtl_modules. This is the FORWARD direction of the wire-attribution predicate
the coverage checker used in reverse — so a child's inter-module ports are
correct-by-construction (specification's main thread injects this into each wave-2
child prompt; children never hand-guess inter-module ports).

Top-level IO ports (§1.4.1) are NOT derived here: §1.4.1 has no owner-module column,
so those stay child-authored and are backstopped by check-coverage's frontmatter
ports ⊆ §1.4.1∪§1.4.2 subset check.

Usage:  python3 scripts/spec/__main__.py derive-ports --workdir <workdir>
Output: JSON {<child_name>: [<wire>, ...], ...} on stdout (sorted, de-duped).
"""

import json
import sys
from pathlib import Path

from spec._md import extract_section, parse_markdown_table

_SEC_142 = r"§?\s*1\.4\.2.*Inter.module\s+Interconnects?"


def _row_endpoints(row: dict) -> set:
    """RTL modules at both ends of a §1.4.2 wire row (template-canonical headers)."""
    producers = {
        p.strip() for p in row.get("Producer (RTL module)", "").split(",") if p.strip()
    }
    consumers = {
        c.strip() for c in row.get("Consumer (RTL module)", "").split(",") if c.strip()
    }
    return producers | consumers


def derive_ports(workdir: Path) -> dict:
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    design_text = (workdir / "design.md").read_text(encoding="utf-8")
    rows = parse_markdown_table(extract_section(design_text, _SEC_142))
    if rows:
        missing = {"Wire", "Producer (RTL module)", "Consumer (RTL module)"} - set(
            rows[0]
        )
        if missing:
            sys.exit(
                f"design.md §1.4.2 table missing canonical column(s) {sorted(missing)} "
                f"(found {list(rows[0])}); see design-template.md."
            )
    out: dict[str, list[str]] = {}
    for child in manifest["children"]:
        rtl_modules = child.get("rtl_modules")
        if not rtl_modules:
            sys.exit(
                f"derive-ports: child {child.get('name')!r} has no rtl_modules[] — "
                f"required to derive inter-module ports. manifest.children[].rtl_modules is a "
                f"hard requirement (specification Completion Gate)."
            )
        owned = set(rtl_modules)
        ports = {
            wire
            for row in rows
            if (wire := row.get("Wire", "").strip()) and owned & _row_endpoints(row)
        }
        out[child["name"]] = sorted(ports)
    return out
