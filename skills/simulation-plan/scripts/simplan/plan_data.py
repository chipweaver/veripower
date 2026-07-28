"""Extract the derived verification universe from a spec workdir into plan-data.json.

The derive-plan-data verb reads a spec workdir (manifest.json + design.md §1.4.x +
check-hints/<child>.json) and emits plan-data.json containing interfaces, check_hints and
cross_module_wires. Clocks, features and timing scenarios are authored as
Design/specification/{clocks,features,timing-scenarios}.json and read from there directly.
The simulation-plan agent consumes plan-data.json to draft verification-plan.md and
scaffold-specification.json; materialize-scaffold reads it to fill the agent signal lists.

Markdown parsing lives in the stage-private simplan._md seam; this module owns the
header-candidate maps + the per-section loaders.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from simplan._md import (
    extract_section,
    map_headers,
    parse_all_markdown_tables,
    parse_first_markdown_table,
    read_text,
    write_text,
)

# ---------------------------------------------------------------------------
# Header candidate mappings.
#
# design.md is produced from skills/specification/references/design-template.md,
# whose H3 headings and table column headers are English. The script matches
# normalized (lowercased, space-stripped, paren-stripped, backtick-stripped)
# header text against these candidate sets.
# ---------------------------------------------------------------------------

INTERFACE_HEADER_CANDIDATES = {
    "signal_name": {"signalname", "signal", "port", "portname"},
    "direction": {"direction", "dir"},
    "width": {"width", "bits"},
    "clock_domain": {"clockdomain", "clock_domain"},
    "interface_group": {"interfacegroup", "interface_group", "group"},
    "protocol": {"protocol"},
    "role": {"role"},
}

# ---------------------------------------------------------------------------
# Spec parsers
# ---------------------------------------------------------------------------


def load_interfaces(design_text: str) -> list[dict]:
    """Extract §1.4.1 Top-Level IO.

    An absent section or table fails loud: every module has top-level IO, and this is the
    guard behind run()'s promise never to write a thin plan-data.json.
    """
    section = extract_section(design_text, r"(^|.*)§?\s*1\.4\.1.*Top.Level\s+IO")
    if not section:
        raise ValueError('design.md "§1.4.1 Top-Level IO" section not found.')
    tables = parse_all_markdown_tables(section)
    if not tables:
        raise ValueError("design.md §1.4.1 Top-Level IO table not found / empty.")

    best: tuple[list[str], list[dict], dict] | None = None
    for headers, rows in tables:
        mapping = map_headers(headers, INTERFACE_HEADER_CANDIDATES)
        if "signal_name" in mapping or "direction" in mapping:
            best = (headers, rows, mapping)
            break
    if best is None:
        headers, rows = tables[0]
        mapping = map_headers(headers, INTERFACE_HEADER_CANDIDATES)
        best = (headers, rows, mapping)

    _, rows, mapping = best
    if "signal_name" not in mapping:
        raise ValueError(
            "design.md §1.4.1 IO table is missing a Signal Name column (mis-named header?)"
        )
    result: list[dict] = []
    for row in rows:
        signal = row.get(mapping.get("signal_name", ""), "").strip()
        if not signal:
            continue
        result.append(
            {
                "signal_name": signal,
                "direction": row.get(mapping.get("direction", ""), "").strip(),
                "width": row.get(mapping.get("width", ""), "").strip() or "1",
                "clock_domain": row.get(mapping.get("clock_domain", ""), "").strip(),
                "interface_group": row.get(
                    mapping.get("interface_group", ""), ""
                ).strip(),
                "protocol": row.get(mapping.get("protocol", ""), "").strip(),
                "role": row.get(mapping.get("role", ""), "").strip(),
            }
        )
    return result


def load_cross_module_wires(design_text: str) -> list[dict]:
    """Extract §1.4.2 Inter-module Interconnects table.

    Returns list of raw row dicts ({Wire, Producer, Consumer, Protocol,
    Timing Constraint, Notes} per design-template header names). Empty list
    when the section is missing or N=1 module has no inter-module wires.
    """
    section = extract_section(
        design_text, r"(^|.*)§?\s*1\.4\.2.*Inter.module\s+Interconnects?"
    )
    if not section:
        return []
    try:
        _, rows = parse_first_markdown_table(section)
    except ValueError:
        return []
    return rows


def load_check_hints(workdir: Path) -> list[dict]:
    """Aggregate every child's check-hints/<child>.json, tagging each hint with its child.

    The per-child split exists because wave-2 children are authored in parallel; the
    aggregate exists because check_id uniqueness and the coverage matrix are global.
    """
    manifest = json.loads((Path(workdir) / "manifest.json").read_text(encoding="utf-8"))
    children = manifest.get("children")
    if not isinstance(children, list) or not children:
        sys.exit("derive-plan-data: manifest.json has no non-empty children[] list")
    hints: list[dict] = []
    seen: dict[str, str] = {}
    for child in children:
        name = child["name"]
        path = Path(workdir) / "check-hints" / f"{name}.json"
        if not path.is_file():
            raise ValueError(f"{path} missing: every child authors its own check hints")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, list):
            raise ValueError(f"{path} must be a JSON array")
        for hint in doc:
            cid = hint.get("check_id")
            if not cid:
                raise ValueError(f"{path} has an entry without check_id")
            if cid in seen:
                raise ValueError(f"duplicate check_id {cid!r}: {seen[cid]} and {name}")
            seen[cid] = name
            hints.append({**hint, "child": name})
    return hints


# ---------------------------------------------------------------------------
# Verb entry
# ---------------------------------------------------------------------------


def run(workdir, output=None) -> int:
    """derive-plan-data: spec workdir -> plan-data.json. Fail-loud non-zero on a
    missing design.md (sys.exit) or a structural defect in a section it does parse;
    never writes a thin/partial plan-data.json."""
    workdir = Path(workdir).resolve()
    design = workdir / "design.md"
    if not design.is_file():
        sys.exit(f"derive-plan-data: missing design.md: {design}")
    output_path = Path(output).resolve() if output else workdir / "plan-data.json"

    # read_text + the load_* helpers raise on a structural defect (decode error in the
    # hand-authored spec, missing sections / columns, missing/malformed manifest.json);
    # convert them to the same clean fail-loud exit the missing-design.md case uses,
    # rather than a raw traceback.
    try:
        design_text = read_text(design)
        check_hints = load_check_hints(workdir)
        interfaces = load_interfaces(design_text)
        cross_module_wires = load_cross_module_wires(design_text)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as e:
        sys.exit(f"derive-plan-data: {e}")

    plan_data = {
        "interfaces": interfaces,
        "check_hints": check_hints,
        "cross_module_wires": cross_module_wires,
    }

    write_text(output_path, json.dumps(plan_data, indent=2, ensure_ascii=False))
    print(f"derive-plan-data: wrote {output_path}")
    print(
        f"  interfaces={len(interfaces)}, check_hints={len(check_hints)}, "
        f"cross_module_wires={len(cross_module_wires)}"
    )
    return 0
