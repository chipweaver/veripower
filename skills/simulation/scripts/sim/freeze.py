#!/usr/bin/env python3
"""sim freeze — materialize a frozen TB into a fresh run workdir.

The deterministic counterpart of `sim bootstrap` for the TB-freeze branch: copy the prior
canonical TB verbatim (incl. the promoted conformance-review.json + verify-handoff.json), then
regenerate only rtl_filelist.f against the current RTL. No scaffold render, no LLM fill -- that
verbatim reuse keeps the checks AND the bin->seq handoff byte-identical across an RTL-only re-run, so
an old-vs-new-RTL comparison varies only the DUT. CWD-anchored design tree (matching bootstrap / state.py).

Exit codes: 0 materialized; 1 fail-closed guard (workdir already populated / missing canonical TB /
missing RTL filelist / missing carry-forward conformance-review.json).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from sim._filelist import rewrite_rtl_filelist

# dirs + files copied verbatim from canonical. NOT per-run outputs, NOT result.json, NOT runs/.
# conformance-review.json + verify-handoff.json ARE copied (both promoted): the verify wave reuses
# the frozen bin->seq handoff (deterministic; no LLM re-derivation) and the prior conformance verdict.
_COPY_DIRS = ("tb", "scripts", "tests")
_COPY_FILES = (
    "Makefile",
    "env.sh",
    "filelist.f",
    "conformance-review.json",
    "verify-handoff.json",
)
# must exist post-copy (carry-forward review + handoff asserted, not silently skipped: P1-A guarantees
# a freeze-eligible baseline has a promoted real review, and both are promoted artifacts).
_REQUIRE = (
    "Makefile",
    "env.sh",
    "filelist.f",
    "rtl_filelist.f",
    "tb/uvm",
    "conformance-review.json",
    "verify-handoff.json",
)


def _err(msg: str) -> None:
    print(f"[sim freeze] {msg}", file=sys.stderr)


def run(module: str, workdir, canonical) -> int:
    tree_root = Path.cwd()
    dest = Path(workdir)
    if not dest.is_absolute():
        dest = tree_root / dest
    dest = Path(str(dest).rstrip("/"))
    canon = Path(canonical)
    if not canon.is_absolute():
        canon = tree_root / canon
    canon = Path(str(canon).rstrip("/"))

    rtl_dir = tree_root / "asic" / module / "Design" / "rtl-design"
    rtl_filelist = rtl_dir / "filelist.txt"
    if not rtl_filelist.is_file():
        _err(f"missing RTL filelist: {rtl_filelist}")
        return 1
    if not (canon / "tb" / "uvm").is_dir():
        _err(f"canonical TB not found: {canon / 'tb' / 'uvm'}")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "Makefile").is_file():
        _err(
            f"workdir already populated (detected {dest / 'Makefile'}); freeze needs a fresh workdir"
        )
        return 1

    # Copy the TB whitelist verbatim.
    for d in _COPY_DIRS:
        src = canon / d
        if src.is_dir():
            shutil.copytree(src, dest / d, dirs_exist_ok=True)
    for f in _COPY_FILES:
        src = canon / f
        if src.is_file():
            shutil.copy2(src, dest / f)

    # Defensive: drop any per-run output dirs that might ride along (normally absent --
    # logs/ and cov_test/ are top-level and not promoted).
    for stale in ("logs", "cov_test"):
        shutil.rmtree(dest / stale, ignore_errors=True)

    # Regenerate rtl_filelist.f against the current RTL (the one thing freeze refreshes).
    rtl_rel = os.path.relpath(rtl_dir, dest)
    rewrite_rtl_filelist(rtl_filelist, dest / "rtl_filelist.f", rtl_rel)

    # Presence assertion (carry-forward conformance-review.json + the TB core).
    for must in _REQUIRE:
        if not (dest / must).exists():
            _err(f"post-copy missing required entry: {must}")
            return 1

    print(
        f"[sim freeze] done — {dest} (TB frozen from {canon}; rtl_filelist regenerated)"
    )
    return 0
