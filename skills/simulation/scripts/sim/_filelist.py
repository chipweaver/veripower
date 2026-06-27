#!/usr/bin/env python3
"""sim rtl-filelist rebase: rewrite Design/rtl-design/filelist.txt -> workdir rtl_filelist.f.

Converts relative RTL paths and +incdir+ / -f directives to paths anchored at rtl_rel
(workdir -> Design/rtl-design relpath). Absolute paths ($ or /) pass through unchanged; other
+/- directives (+define+, -define) pass through unchanged. Private lib for the bootstrap verb
(the caller verifies the source exists). Per-stage copy (campaign §3)."""

from __future__ import annotations

from pathlib import Path


def rewrite_rtl_filelist(src, dst, rtl_rel: str) -> None:
    src, dst = Path(src), Path(dst)
    out: list[str] = []
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            out.append("")
            continue
        if line.startswith("#"):
            out.append(raw)
            continue
        if line.startswith("+incdir+"):
            path = line[len("+incdir+") :]
            if path.startswith("/") or path.startswith("$"):
                out.append(line)
            else:
                out.append(f"+incdir+{rtl_rel}/{path}")
            continue
        if line.startswith("-f "):
            path = line[3:].strip()
            if path.startswith("/") or path.startswith("$"):
                out.append(line)
            else:
                out.append(f"-f {rtl_rel}/{path}")
            continue
        if line.startswith("+") or line.startswith("-"):
            out.append(line)
            continue
        if line.startswith("/") or line.startswith("$"):
            out.append(line)
        else:
            out.append(f"{rtl_rel}/{line}")
    dst.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
