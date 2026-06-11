#!/usr/bin/env python3
"""Extract structured verification data from a spec workdir into plan-data.json.

Reads a spec workdir (manifest.json + design.md + per-child <child>.md) and emits
plan-data.json containing features, interfaces, scenarios, check_hints, and clocks. The
simulation-plan agent consumes this to draft verification-plan.md and
scaffold-specification.json.

Sibling script:
- derive_scaffold.py — reads scaffold-specification.json (produced by the
  simulation-plan agent after Plan Gate) and emits the full UVM scaffold.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Header candidate mappings.
#
# design.md is produced from skills/specification/references/design-template.md,
# whose H3 headings and table column headers are English. The script matches
# normalized (lowercased, space-stripped, paren-stripped, backtick-stripped)
# header text against these candidate sets.
# ---------------------------------------------------------------------------

FEATURE_HEADER_CANDIDATES = {
    "feature_id": {"id", "featureid"},
    "feature_name": {"feature", "featurename", "name"},
    "description": {"description", "desc", "notes"},
    "mode_interface": {"mode/interface", "interface", "mode"},
    "priority": {"priority"},
    "happy_path": {"happypath", "happy_path", "happy"},
    "corner_cases": {"cornercases", "corner_cases", "corner"},
    "negative_cases": {"negativecases", "negative_cases", "negative"},
    "coverage_intent": {"coverageintent", "coverage_intent", "coverage"},
}

CLOCK_HEADER_CANDIDATES = {
    "clock_name": {"clockname", "clock"},
    "description": {"description"},
    "frequency": {"nominalfrequency", "frequency"},
    "period_ns": {"sdcperiod", "periodns", "period"},
    "relationship": {"relationship"},
}

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
# Low-level helpers
# ---------------------------------------------------------------------------


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def normalize_header(raw: str) -> str:
    lowered = raw.strip().lower()
    lowered = lowered.replace("`", "")
    lowered = lowered.replace(" ", "")
    lowered = re.sub(r"\([^)]*\)", "", lowered)
    return lowered


def extract_section(text: str, heading_pattern: str) -> str:
    lines = text.splitlines()
    capture = False
    level: int | None = None
    collected: list[str] = []
    matcher = re.compile(heading_pattern)
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if capture and len(heading.group(1)) <= (level or 6):
                break
            if matcher.search(heading.group(2)):
                capture = True
                level = len(heading.group(1))
                continue
        if capture:
            collected.append(line)
    return "\n".join(collected).strip()


def parse_first_markdown_table(section: str) -> tuple[list[str], list[dict]]:
    lines = section.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip().startswith("|"):
            current.append(line.rstrip())
        else:
            if len(current) >= 2:
                blocks.append(current)
            current = []
    if len(current) >= 2:
        blocks.append(current)
    if not blocks:
        raise ValueError("no Markdown table found.")

    table = blocks[0]
    headers = [cell.strip() for cell in table[0].strip().strip("|").split("|")]
    rows: list[dict] = []
    for line in table[2:]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        rows.append(dict(zip(headers, cells[: len(headers)])))
    return headers, rows


def parse_all_markdown_tables(section: str) -> list[tuple[list[str], list[dict]]]:
    """Return all Markdown tables in a section as list of (headers, rows)."""
    lines = section.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip().startswith("|"):
            current.append(line.rstrip())
        else:
            if len(current) >= 2:
                blocks.append(current)
            current = []
    if len(current) >= 2:
        blocks.append(current)

    results: list[tuple[list[str], list[dict]]] = []
    for table in blocks:
        try:
            headers = [cell.strip() for cell in table[0].strip().strip("|").split("|")]
            rows: list[dict] = []
            for line in table[2:]:
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if len(cells) < len(headers):
                    cells.extend([""] * (len(headers) - len(cells)))
                rows.append(dict(zip(headers, cells[: len(headers)])))
            results.append((headers, rows))
        except (IndexError, ValueError):
            continue
    return results


def map_headers(headers: list[str], candidates: dict[str, set[str]]) -> dict[str, str]:
    mapping = {}
    for header in headers:
        normalized = normalize_header(header)
        for key, aliases in candidates.items():
            if normalized in aliases:
                mapping[key] = header
    return mapping


def default_if_blank(value: str, fallback: str) -> str:
    return value.strip() if value and value.strip() else fallback


# ---------------------------------------------------------------------------
# Spec parsers
# ---------------------------------------------------------------------------


def load_features(design_text: str) -> list[dict]:
    """English canonical anchor — §1.3 Feature Table."""
    section = extract_section(design_text, r"(^|.*)§?\s*1\.3.*Feature\s+Table")
    if not section:
        raise ValueError('design.md "§1.3 Feature Table" section not found.')
    headers, rows = parse_first_markdown_table(section)
    mapping = map_headers(headers, FEATURE_HEADER_CANDIDATES)
    required = {"feature_id", "feature_name", "description"}
    missing = required - mapping.keys()
    if missing:
        raise ValueError(
            f"design.md §1.3 features table is missing required columns: {', '.join(sorted(missing))}"
        )

    features: list[dict] = []
    for row in rows:
        feature_id = row[mapping["feature_id"]].strip()
        feature_name = row[mapping["feature_name"]].strip()
        description = row[mapping["description"]].strip()
        if not feature_id or not feature_name:
            continue
        features.append(
            {
                "feature_id": feature_id,
                "feature_name": feature_name,
                "description": description,
                "mode_interface": default_if_blank(
                    row.get(mapping.get("mode_interface", ""), ""), "unspecified"
                ),
                "priority": default_if_blank(
                    row.get(mapping.get("priority", ""), ""), ""
                ),
                "happy_path": default_if_blank(
                    row.get(mapping.get("happy_path", ""), ""),
                    f"Verify {feature_name}'s main-path behavior conforms to spec.",
                ),
                "corner_cases": default_if_blank(
                    row.get(mapping.get("corner_cases", ""), ""),
                    "",
                ),
                "negative_cases": default_if_blank(
                    row.get(mapping.get("negative_cases", ""), ""),
                    "",
                ),
                "coverage_intent": default_if_blank(
                    row.get(mapping.get("coverage_intent", ""), ""),
                    "feature traceability",
                ),
            }
        )
    if not features:
        raise ValueError("design.md §1.3 features table is empty.")
    return features


def load_clock_table(design_text: str) -> list[dict]:
    """English canonical anchor — §1.6 Clocks and Frequencies."""
    section = extract_section(design_text, r"(^|.*)§?\s*1\.6.*Clocks?\s+and\s+Freq")
    if not section:
        return []
    try:
        headers, rows = parse_first_markdown_table(section)
    except ValueError:
        return []
    mapping = map_headers(headers, CLOCK_HEADER_CANDIDATES)
    result: list[dict] = []
    for row in rows:
        result.append(
            {
                "clock_name": row.get(mapping.get("clock_name", ""), ""),
                "description": row.get(mapping.get("description", ""), ""),
                "frequency": row.get(mapping.get("frequency", ""), ""),
                "period_ns": row.get(mapping.get("period_ns", ""), ""),
                "relationship": row.get(mapping.get("relationship", ""), ""),
            }
        )
    return result


def load_interfaces(design_text: str) -> list[dict]:
    """Extract §1.4.1 Top-Level IO."""
    section = extract_section(design_text, r"(^|.*)§?\s*1\.4\.1.*Top.Level\s+IO")
    if not section:
        return []
    tables = parse_all_markdown_tables(section)
    if not tables:
        return []

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
    hints: list[dict] = []
    for child in manifest["children"]:
        sub_text = (Path(workdir) / child["doc"]).read_text(encoding="utf-8")
        section = extract_section(sub_text, r"(^|.*)§?\s*5\.?\s*Verification\s+Hints?")
        if not section:
            continue
        try:
            _, rows = parse_first_markdown_table(section)
        except ValueError:
            continue
        for row in rows:
            h = _normalize_check_hint_row(row)
            if h is None:
                continue
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
# CLI + main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract plan-data.json from a spec workdir."
    )
    p.add_argument(
        "--workdir",
        required=True,
        help="Spec workdir containing manifest.json + design.md + <child>.md.",
    )
    p.add_argument(
        "--output",
        required=False,
        help="Direct output path (default: <workdir>/plan-data.json).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    workdir = Path(args.workdir).resolve()
    design = workdir / "design.md"
    if not design.is_file():
        sys.exit(f"derive_plan_data: missing design.md: {design}")
    design_text = read_text(design)
    check_hints = load_check_hints(workdir)
    output_path = (
        Path(args.output).resolve() if args.output else workdir / "plan-data.json"
    )

    features = load_features(design_text)
    clocks = load_clock_table(design_text)
    interfaces = load_interfaces(design_text)
    scenarios = load_scenarios(design_text)
    cross_module_wires = load_cross_module_wires(design_text)

    plan_data: dict = {
        "features": features,
        "interfaces": interfaces,
        "scenarios": scenarios,
        "check_hints": check_hints,
        "clocks": clocks,
        "cross_module_wires": cross_module_wires,
    }

    write_text(output_path, json.dumps(plan_data, indent=2, ensure_ascii=False))
    print(f"derive_plan_data: wrote {output_path}")
    print(
        f"  features={len(features)}, interfaces={len(interfaces)}, "
        f"scenarios={len(scenarios)}, check_hints={len(check_hints)}, "
        f"clocks={len(clocks)}, cross_module_wires={len(cross_module_wires)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
