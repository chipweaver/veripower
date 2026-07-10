#!/usr/bin/env python3
"""sim copy-baseline — seed a fresh run workdir from the prior canonical TB.

Serves two modes (selected by the --mode argument to the copy-baseline verb):

  freeze mode (default): copy the prior canonical TB verbatim, including the promoted
    conformance-review.json + verify-handoff.json, then regenerate rtl_filelist.f against the
    current RTL. No scaffold render, no LLM fill -- that verbatim reuse keeps the checks AND the
    bin->seq handoff byte-identical across an RTL-only re-run, so an old-vs-new-RTL comparison
    varies only the DUT. Requires the judged artifacts to be present (P1-A carry-forward assertion).

  patch mode: copy only the TB code (Makefile, env.sh, filelist.f, tb/uvm) and regenerate
    rtl_filelist.f. Does NOT copy or require the judged artifacts (conformance-review.json /
    verify-handoff.json): a smoke/compile-failed baseline has none, and the patch child
    re-authors them anyway via a full conformance re-run.

Both modes use CWD-anchored design tree (matching bootstrap / kernel.py).

Exit codes: 0 materialized; 1 fail-closed guard (workdir already populated / missing canonical TB /
missing RTL filelist / missing a required carry-forward).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from sim._filelist import rewrite_rtl_filelist

# dirs + files copied verbatim from canonical. NOT per-run outputs, NOT result.json, NOT runs/.
_COPY_DIRS = ("tb", "scripts", "tests")
# freeze mode carries the judged artifacts (verbatim reuse, conformance skipped downstream);
# patch mode copies TB code only -- the patch child re-authors and full conformance re-runs.
_COPY_FILES = {
    "freeze": (
        "Makefile",
        "env.sh",
        "filelist.f",
        "conformance-review.json",
        "verify-handoff.json",
    ),
    "patch": ("Makefile", "env.sh", "filelist.f"),
}
# must exist post-copy (carry-forward review + handoff asserted, not silently skipped: P1-A guarantees
# a freeze-eligible baseline has a promoted real review, and both are promoted artifacts).
_REQUIRE = {
    "freeze": (
        "Makefile",
        "env.sh",
        "filelist.f",
        "rtl_filelist.f",
        "tb/uvm",
        "conformance-review.json",
        "verify-handoff.json",
    ),
    "patch": ("Makefile", "env.sh", "filelist.f", "rtl_filelist.f", "tb/uvm"),
}


def _err(msg: str) -> None:
    print(f"[sim copy-baseline] {msg}", file=sys.stderr)


def run(module: str, workdir, canonical, mode: str = "freeze") -> int:
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
            f"workdir already populated (detected {dest / 'Makefile'}); {mode} needs a fresh workdir"
        )
        return 1

    # Copy the TB whitelist verbatim.
    for d in _COPY_DIRS:
        src = canon / d
        if src.is_dir():
            shutil.copytree(src, dest / d, dirs_exist_ok=True)
    for f in _COPY_FILES[mode]:
        src = canon / f
        if src.is_file():
            shutil.copy2(src, dest / f)

    # Regenerate rtl_filelist.f against the current RTL (the one thing freeze refreshes).
    rtl_rel = os.path.relpath(rtl_dir, dest)
    rewrite_rtl_filelist(rtl_filelist, dest / "rtl_filelist.f", rtl_rel)

    # Presence assertion (carry-forward conformance-review.json + the TB core).
    for must in _REQUIRE[mode]:
        if not (dest / must).exists():
            _err(f"post-copy missing required entry: {must}")
            return 1

    tb_state = "frozen" if mode == "freeze" else "seeded"
    print(
        f"[sim copy-baseline] done — {dest} (TB {tb_state} from {canon}; rtl_filelist regenerated)"
    )
    return 0
