"""Markdown section + table helpers shared across spec verbs.

extract_section + parse_markdown_table are the ONLY two helpers imported by
more than one verb (coverage / ports / constraints), so they live here.
parse_frontmatter / _is_blank / _blank_or_dash stay private to coverage.py
(its sole consumer). Stage-internal dedup only — rtl-design / simulation-plan
keep their own copies (skills stay decoupled; design §1 non-goals).
"""

import re

_PIPE = re.compile(r"(?<!\\)\|")


def _split_row(line: str) -> list[str]:
    """Split a Markdown table row on UNescaped '|' (a literal pipe in a cell is
    written '\\|'); unescape '\\|' -> '|' and trim each cell. Without honoring the
    escape, a cell quoting a pipe over-splits and every column after it shifts right."""
    parts = _PIPE.split(line.strip())
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    return [p.replace("\\|", "|").strip() for p in parts]


def extract_section(text: str, heading_regex: str) -> str:
    """Return markdown content from matching heading until next same-or-shallower heading."""
    out = []
    in_sec = False
    sec_depth = None
    pat = re.compile(heading_regex)
    for line in text.splitlines():
        h = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if h:
            depth = len(h.group(1))
            if pat.search(h.group(2)):
                in_sec = True
                sec_depth = depth
                continue
            if in_sec and depth <= sec_depth:
                break
        if in_sec:
            out.append(line)
    return "\n".join(out)


def parse_markdown_table(section_text: str) -> list[dict]:
    """Parse the first markdown table after a heading; return list of row dicts."""
    rows: list[dict] = []
    header: list[str] | None = None
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
