"""Extract the derived verification universe from a spec workdir into plan-data.json.

The derive-plan-data verb reads a spec workdir (manifest.json + design.md + per-child
<child>.md) and emits plan-data.json containing features, interfaces, scenarios,
check_hints, and cross_module_wires. Clocks and features are not here — they are
authored as Design/specification/{clocks,features}.json and read from there. The simulation-plan agent consumes this to
draft verification-plan.md and scaffold-specification.json; the materialize-scaffold verb
then reads plan-data.json to fill the agent signal lists.

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

# The §5 heading selector. specification's check-coverage gate reads the SAME section out of
# the same child docs and has already validated its gated columns, so the two patterns must
# stay byte-identical: anything the gate accepts, this consumer must read rather than skip.
# tests/contracts/test_cross_stage_contracts.py locks them equal.
SEC5_HINTS_HEADING = r"§?\s*5\b.*Verification\s+Hints?"

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

SCENARIO_HEADER_CANDIDATES = {
    "scenario_id": {"scenarioid", "scenario_id", "sceneid"},
    "interface_mode": {"interface/mode", "interface"},
    "stimulus": {"trigger/stimulus", "stimulus", "trigger"},
    "expected": {"expectedresult", "expected", "result"},
    "timing_constraint": {"timingconstraint", "timing_constraint"},
    "exception": {"exceptions/negativecases", "exception", "negative"},
}

CHECK_HINT_HEADER_CANDIDATES = {
    "check_id": {"checkid", "check_id"},
    "source_feature": {"sourcefeature", "source_feature", "sourceid", "featureid"},
    "implementation_detail": {
        "implementationdetail",
        "implementation_detail",
        "detail",
        "implementation",
    },
    "implementation_detail_verbatim": {
        "implementationdetailverbatim",
        "implementation_detail_verbatim",
        "verbatim",
    },
    "observable": {"observable"},
    "reference_rule": {"referencerule", "reference_rule", "rule"},
    "latency": {"latency", "cycles"},
    "reset_behavior": {"resetbehavior", "reset_behavior", "reset"},
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


def load_scenarios(design_text: str) -> list[dict]:
    """English canonical anchor — §1.5 Interface Timing Scenarios."""
    section = extract_section(
        design_text, r"(^|.*)§?\s*1\.5.*Interface\s+Timing\s+Scenarios?"
    )
    if not section:
        return []
    tables = parse_all_markdown_tables(section)
    if not tables:
        return []

    result: list[dict] = []
    for headers, rows in tables:
        mapping = map_headers(headers, SCENARIO_HEADER_CANDIDATES)
        if "scenario_id" not in mapping and "stimulus" not in mapping:
            continue
        for row in rows:
            scenario_id = row.get(mapping.get("scenario_id", ""), "").strip()
            if not scenario_id:
                continue
            result.append(
                {
                    "scenario_id": scenario_id,
                    "interface_mode": row.get(
                        mapping.get("interface_mode", ""), ""
                    ).strip(),
                    "stimulus": row.get(mapping.get("stimulus", ""), "").strip(),
                    "expected": row.get(mapping.get("expected", ""), "").strip(),
                    "timing_constraint": row.get(
                        mapping.get("timing_constraint", ""), ""
                    ).strip(),
                    "exception": row.get(mapping.get("exception", ""), "").strip(),
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
    """Iterate manifest.children, read each <child>.md §5 Verification Hints,
    tag each hint with the `child` field. manifest.json is a required input
    (the specification skill always emits it); a missing one fails loud.
    """
    manifest = json.loads((Path(workdir) / "manifest.json").read_text(encoding="utf-8"))
    children = manifest.get("children")
    if not isinstance(children, list) or not children:
        sys.exit("derive-plan-data: manifest.json has no non-empty children[] list")
    hints: list[dict] = []
    seen: dict[str, str] = {}
    for child in children:
        sub_text = (Path(workdir) / child["doc"]).read_text(encoding="utf-8")
        section = extract_section(sub_text, SEC5_HINTS_HEADING)
        if not section:
            continue
        try:
            headers, rows = parse_first_markdown_table(section)
        except ValueError:
            continue
        # A child that HAS a §5 table but whose Check-ID header is mis-named (e.g.
        # `Check-ID`, which normalize_header does not strip to `checkid`) would yield
        # zero hints silently, dropping that child's entire hint set from the coverage
        # gate. Read the declared header once; a missing Check ID column fails loud.
        if "check_id" not in map_headers(headers, CHECK_HINT_HEADER_CANDIDATES):
            raise ValueError(
                f"{child['name']} §5 table has no Check ID column (mis-named header?)"
            )
        for row in rows:
            h = _normalize_check_hint_row(row)
            if h is None:
                continue
            cid = h["check_id"]
            if cid in seen:
                raise ValueError(
                    f"duplicate check_id {cid!r} across <child>.md §5 tables"
                )
            seen[cid] = child["name"]
            h["child"] = child["name"]
            hints.append(h)
    return hints


def _normalize_check_hint_row(row: dict) -> dict | None:
    """Map a raw markdown-row dict (header keys) to the canonical check_hint dict."""
    headers = list(row.keys())
    mapping = map_headers(headers, CHECK_HINT_HEADER_CANDIDATES)
    if "check_id" not in mapping and "source_feature" not in mapping:
        return None
    check_id = row.get(mapping.get("check_id", ""), "").strip()
    if not check_id:
        return None
    return {
        "check_id": check_id,
        "source_feature": row.get(mapping.get("source_feature", ""), "").strip(),
        "implementation_detail": row.get(
            mapping.get("implementation_detail", ""), ""
        ).strip(),
        "implementation_detail_verbatim": row.get(
            mapping.get("implementation_detail_verbatim", ""), ""
        ).strip(),
        "observable": row.get(mapping.get("observable", ""), "").strip(),
        "reference_rule": row.get(mapping.get("reference_rule", ""), "").strip(),
        "latency": row.get(mapping.get("latency", ""), "").strip(),
        "reset_behavior": row.get(mapping.get("reset_behavior", ""), "").strip(),
    }


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
        scenarios = load_scenarios(design_text)
        cross_module_wires = load_cross_module_wires(design_text)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as e:
        sys.exit(f"derive-plan-data: {e}")

    plan_data = {
        "interfaces": interfaces,
        "scenarios": scenarios,
        "check_hints": check_hints,
        "cross_module_wires": cross_module_wires,
    }

    write_text(output_path, json.dumps(plan_data, indent=2, ensure_ascii=False))
    print(f"derive-plan-data: wrote {output_path}")
    print(
        f"  interfaces={len(interfaces)}, scenarios={len(scenarios)}, "
        f"check_hints={len(check_hints)}, cross_module_wires={len(cross_module_wires)}"
    )
    return 0
