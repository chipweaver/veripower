#!/usr/bin/env python3
"""rtl seed — carry prior canonical rtl-design artifacts into a rework/incremental workdir.

Copies every prior canonical file into the workdir with NO-CLOBBER semantics (cp -n): a
file already present in the workdir (freshly authored on a session-resume) is never
overwritten (resume-idempotent). This carries unchanged children's RTL forward so the
framework's promote step — which copies only artifacts[] and GC-removes absentees — neither
loses RTL nor crashes on a subset rework. First-run (no canonical dir) is a no-op.

The canonical dir contains a `runs/` subtree (prior run workdirs); it is skipped.
Canonical defaults to `{workdir}/../..`: the framework lays the workdir at
`<...>/Design/rtl-design/runs/<N>`, so the stage's canonical dir is the grandparent.
"""

from __future__ import annotations

import json
import shutil
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


def run(workdir, canonical=None) -> int:
    workdir = Path(workdir)
    canonical = (
        Path(canonical) if canonical is not None else workdir.resolve().parent.parent
    )
    copied = seed(canonical, workdir)
    print(json.dumps({"seeded": copied, "count": len(copied)}, ensure_ascii=False))
    return 0
