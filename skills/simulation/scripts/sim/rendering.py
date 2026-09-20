#!/usr/bin/env python3
"""sim render primitives: strict {{KEY}} template renderer, file I/O, and SV emission.

Render/IO/SV-emit half of the scaffold generator. The strict renderer raises on any
unresolved {{KEY}} rather than letting it through into SV output; the syntax is {{KEY}} and
not {KEY} because SystemVerilog uses single braces heavily (`{8'h0F, x}`).
"""

from __future__ import annotations

import re
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def render_template_file(
    template_dir: Path, template_name: str, mapping: dict[str, str]
) -> str:
    template_path = template_dir / template_name
    text = template_path.read_text(encoding="utf-8")
    return PLACEHOLDER_RE.sub(lambda match: str(mapping[match.group(1)]), text)


def signal_declarations(signals: list[dict]) -> str:
    """Use nets for bidirectional connections and variables for other data ports."""
    lines = []
    for sig in signals:
        name = sig["name"]
        width = sig["width"]
        kind = "wire" if sig["direction"] == "inout" else "logic"
        if width > 1:
            lines.append(f"  {kind} [{width - 1}:0] {name};")
        else:
            lines.append(f"  {kind}        {name};")
    return "\n".join(lines)
