#!/usr/bin/env python3
"""Seed a fresh rework/incremental workdir from prior canonical rtl-design artifacts.

Copies every prior canonical file into the workdir with NO-CLOBBER semantics (cp -n): a
file already present in the workdir (freshly authored on a session-resume) is never
overwritten (resume-idempotent). This carries unchanged children's RTL forward so the
framework's promote step — which copies only artifacts[] and GC-removes absentees — neither
loses RTL nor crashes on a subset rework. First-run (no canonical dir) is a no-op.

The canonical dir contains a `runs/` subtree (prior run workdirs); it is skipped.

Canonical defaults to `{workdir}/../..`: the framework lays the workdir at
`<...>/Design/rtl-design/runs/<N>`, so the stage's canonical dir is the grandparent. This
avoids a hardcoded per-module path fragment in the caller and is internally consistent with
the `runs/` self-copy skip below.

Usage: seed_rework.py --workdir <runs/N> [--canonical <dir>]   # --canonical defaults to workdir/../..
Exit: 0 always (no-op when canonical is absent — first-run).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def seed(canonical: Path, workdir: Path) -> list:
    copied: list = []
    if not canonical.is_dir():
        return copied
    for src in sorted(canonical.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(canonical)
        if rel.parts and rel.parts[0] == "runs":  # never carry prior run workdirs
            continue
        dst = workdir / rel
        if dst.exists():  # no-clobber: keep freshly-authored work
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(rel))
    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument(
        "--canonical",
        type=Path,
        default=None,
        help="prior canonical dir; default = {workdir}/../..",
    )
    a = ap.parse_args()
    canonical = (
        a.canonical if a.canonical is not None else a.workdir.resolve().parent.parent
    )
    copied = seed(canonical, a.workdir)
    print(json.dumps({"seeded": copied, "count": len(copied)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
