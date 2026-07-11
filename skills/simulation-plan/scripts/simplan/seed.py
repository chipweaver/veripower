#!/usr/bin/env python3
"""simplan seed — carry prior canonical verification-plan artifacts into a freeze/rework workdir.

Copies every prior canonical file into the workdir with NO-CLOBBER semantics (a file
already present is never overwritten — resume-idempotent), skipping the `runs/` subtree.
On the freeze branch this byte-copies verification-plan.md / scaffold-specification.json
AND plan-review.json forward, so a `pin` on the review record survives. First-run (no
canonical dir) is a no-op. Canonical defaults to `{workdir}/../..` (workdir is runs/<N>).
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
