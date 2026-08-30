#!/usr/bin/env python3
"""Rewrite simulation/filelist.f into a GLS-friendly absolutized filelist.

Drops the `-f rtl_filelist.f` line (the synthesis netlist replaces the RTL).
Converts relative `tb/uvm/...` paths and `+incdir+tb/uvm/...` directives to
absolute paths against the simulation TB directory, so VCS can be invoked
from this stage's workdir without cd-ing into the simulation dir.

Any other list the bench pulls in is inlined rather than referenced: it names sources this
stage compiles too, and its paths are relative to the simulation directory, which is not where
this stage runs.
"""

from __future__ import annotations

import argparse
import os
import re
import sys


def absolutize(lines: list[str], tb: str, acc: list[str]) -> None:
    """Rewrite one filelist's lines into acc, following the lists it pulls in."""
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            acc.append(line)
            continue
        if s.startswith("-f "):
            ref = s[3:].strip()
            if ref.endswith("rtl_filelist.f"):
                continue  # the GLS netlist replaces the RTL
            sub = ref if ref.startswith("/") else os.path.join(tb, ref)
            with open(sub) as f:
                absolutize(f.read().splitlines(), tb, acc)
            continue
        m = re.match(r"(\+incdir\+)(.+)", s)
        if m:
            inc = m.group(2)
            if not (inc.startswith("$") or inc.startswith("/")):
                acc.append(f"+incdir+{tb}/{inc}")
                continue
            acc.append(line)
            continue
        if not s.startswith("$") and not s.startswith("/") and not s.startswith("-"):
            acc.append(f"{tb}/{s}")
            continue
        acc.append(line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tb-dir", required=True, help="Path to Verification/simulation/")
    ap.add_argument("--out", required=True, help="Output absolutized filelist path")
    ns = ap.parse_args()

    tb = os.path.realpath(ns.tb_dir)
    src = os.path.join(tb, "filelist.f")
    if not os.path.isfile(src):
        print(
            f"[build_tb_filelist_abs] ERROR: source filelist not found: {src}",
            file=sys.stderr,
        )
        return 1

    with open(src) as f:
        lines = f.read().splitlines()

    acc: list[str] = []
    absolutize(lines, tb, acc)

    with open(ns.out, "w") as f:
        f.write("\n".join(acc) + "\n")
    print(f"[build_tb_filelist_abs] wrote {ns.out} ({len(acc)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
