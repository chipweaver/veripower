#!/usr/bin/env python3
"""sim render primitives: strict {{KEY}} template renderer, file I/O, and SV emission.

Render/IO/SV-emit half of the scaffold generator. The strict renderer raises on any
unresolved {{KEY}} rather than letting it through into SV output; the syntax is {{KEY}} and
not {KEY} because SystemVerilog uses single braces heavily (`{8'h0F, x}`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _render_strict(text: str, mapping: dict[str, str]) -> str:
    """Replace every {{KEY}} placeholder using mapping. Raises KeyError on unknown key."""

    def repl(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key not in mapping:
            raise KeyError(f"Unresolved placeholder {{{{{key}}}}} in template")
        return str(mapping[key])

    return _PLACEHOLDER_RE.sub(repl, text)


def _render_template_file(
    template_dir: Path, template_name: str, mapping: dict[str, str]
) -> str:
    tmpl_path = template_dir / template_name
    if not tmpl_path.is_file():
        sys.exit(f"[sim bootstrap] missing template file: {tmpl_path}")
    return _render_strict(tmpl_path.read_text(encoding="utf-8"), mapping)


def _signal_declarations(signals: list[dict]) -> str:
    """Generate SystemVerilog signal declarations from interface signal list."""
    lines = []
    for sig in signals:
        name = sig["name"]
        width = int(sig.get("width", 1))
        if width > 1:
            lines.append(f"  logic [{width - 1}:0] {name};")
        else:
            lines.append(f"  logic        {name};")
    return "\n".join(lines)


def _field_declarations(fields: list[dict]) -> str:
    """Generate transaction field declarations."""
    lines = []
    for f in fields:
        name = f["name"]
        typ = f.get("type", "logic")
        width = int(f.get("width", 1))
        rand_prefix = "rand " if f.get("rand", False) else ""
        if typ in ("int", "int unsigned"):
            lines.append(f"  {rand_prefix}{typ} {name};")
        elif width > 1:
            lines.append(f"  {rand_prefix}logic [{width - 1}:0] {name};")
        else:
            lines.append(f"  {rand_prefix}logic        {name};")
    return "\n".join(lines)


def _field_macros(fields: list[dict]) -> str:
    """Generate `uvm_field_int macros for transaction fields."""
    lines = []
    for f in fields:
        lines.append(f"    `uvm_field_int({f['name']}, UVM_ALL_ON)")
    return "\n".join(lines)
