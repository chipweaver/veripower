"""Markdown section + table helpers for the derive-plan-data verb.

The parsing seam extracted from the 501-line god-file: read_text, write_text,
normalize_header, extract_section, parse_first_markdown_table,
parse_all_markdown_tables, map_headers, default_if_blank. STAGE-PRIVATE — only
plan_data.py consumes these. Stage-internal dedup only: specification and
rtl-design keep their own copies (skills stay decoupled; design §1 non-goals).
"""

from __future__ import annotations

import re
from pathlib import Path


def read_text(path: Path) -> str:
    # A hand-authored spec is the input here; a decode error must fail loud (the verb's
    # run() maps it to a clean exit), never be papered over by dropping bytes.
    return path.read_text(encoding="utf-8")


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
