#!/usr/bin/env python3
"""simplan seed — carry prior canonical verification-plan PRODUCTS into a rework/freeze workdir.

Whitelist copy with NO-CLOBBER semantics (a file already present is never overwritten —
resume-idempotent): verification-plan.md and scaffold-specification.json. Adjudication
artifacts are excluded by construction (room-birth hygiene, ARCHITECTURE §7.2):
result.json is never seeded (a carried-in stale envelope is reaped blocked/stale_result),
and plan-data.json is re-derived every branch by derive-plan-data. The judged review
record (plan-review.json) is copied ONLY with --freeze — the freeze branch's byte-carry
that keeps a `pin` on the record alive. First-run (no canonical dir) is a no-op.
Canonical defaults to `{workdir}/../..` (workdir is runs/<N>).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

PRODUCTS = ("verification-plan.md", "scaffold-specification.json")
FREEZE_EXTRAS = ("plan-review.json",)


def seed(canonical: Path, workdir: Path, freeze: bool = False) -> list:
    copied: list = []
    if not canonical.is_dir():
        return copied
    for g in PRODUCTS + (FREEZE_EXTRAS if freeze else ()):
        for src in sorted(canonical.glob(g)):
            if not src.is_file():
                continue
            rel = src.relative_to(canonical)
            dst = workdir / rel
            if dst.exists():  # no-clobber: keep freshly-authored work
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(str(rel))
    return copied


def run(workdir, canonical=None, freeze: bool = False) -> int:
    workdir = Path(workdir)
    canonical = (
        Path(canonical) if canonical is not None else workdir.resolve().parent.parent
    )
    copied = seed(canonical, workdir, freeze=freeze)
    print(json.dumps({"seeded": copied, "count": len(copied)}, ensure_ascii=False))
    return 0
