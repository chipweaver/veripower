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
import sys
from pathlib import Path

from simplan.classify import products_digest

PRODUCTS = ("verification-plan.md", "scaffold-specification.json")
FREEZE_EXTRAS = ("plan-review.json",)


def _freeze_carry_error(canonical: Path, workdir: Path) -> str | None:
    """Freeze-carry verification — closes the check-then-copy window: classify-delta
    proved the canonical products matched the recorded digest at Step 1, but the bytes
    that matter are the ones seed just copied. Recompute over the WORKDIR copies against
    the canonical-recorded digest; a mismatch means the canonical drifted mid-run or the
    workdir held residue (no-clobber kept it), and the freeze must not proceed. A legacy
    canonical without a recorded digest is skipped — classify-delta already refuses to
    classify it freeze."""
    try:
        rj = json.loads((canonical / "result.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None  # no canonical envelope -> nothing recorded to verify against
    if not isinstance(rj, dict):
        return None
    ss = rj.get("stage_specific", {})
    recorded = ss.get("products_digest") if isinstance(ss, dict) else None
    if recorded is None:
        return None
    paths = [
        a.get("path")
        for a in rj.get("artifacts", [])
        if isinstance(a, dict) and isinstance(a.get("path"), str) and a.get("path")
    ]
    try:
        current = products_digest(workdir, paths)
    except (OSError, ValueError) as exc:
        return f"carried product unreadable: {exc}"
    if current != recorded:
        return (
            "carried bytes do not match the canonical-recorded products_digest "
            "(canonical drifted mid-run, or the workdir was not empty)"
        )
    return None


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
    if freeze:
        err = _freeze_carry_error(canonical, workdir)
        if err:
            print(f"[simplan seed] FAIL=freeze-carry {err}", file=sys.stderr)
            return 2
    print(json.dumps({"seeded": copied, "count": len(copied)}, ensure_ascii=False))
    return 0
