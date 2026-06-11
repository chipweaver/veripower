#!/usr/bin/env python3
"""Rewrite Design/rtl-design/filelist.txt → workdir's rtl_filelist.f.

Converts relative RTL paths and `+incdir+` / `-f` directives to paths anchored at
RTL_REL_DIR (relpath from workdir to Design/rtl-design/). Absolute paths
(starting with `/` or `$`) pass through unchanged. Other `+`/`-` directives
(`+define+`, `-define`) pass through unchanged.

Called by bootstrap_simulation.sh on first deploy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--src", required=True, type=Path, help="Path to Design/rtl-design/filelist.txt"
    )
    p.add_argument(
        "--dst", required=True, type=Path, help="Output path for rtl_filelist.f"
    )
    p.add_argument(
        "--rtl-rel", required=True, help="relpath(asic/<M>/Design/rtl-design, workdir)"
    )
    args = p.parse_args()

    if not args.src.is_file():
        print(
            f"[build_rtl_filelist] ERROR: source filelist not found: {args.src}",
            file=sys.stderr,
        )
        return 1

    rtl_rel = args.rtl_rel
    out: list[str] = []
    for raw in args.src.read_text(encoding="utf-8").splitlines():
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
    args.dst.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
