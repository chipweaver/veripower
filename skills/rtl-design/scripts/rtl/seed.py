#!/usr/bin/env python3
"""rtl seed — carry prior canonical rtl-design PRODUCTS into a rework/incremental workdir.

Whitelist copy with NO-CLOBBER semantics (cp -n): a file already present in the workdir
(freshly authored on a session-resume) is never overwritten (resume-idempotent). The
product set is the union of (a) HDL files by suffix (.v/.sv/.vh/.svh, any depth —
children author their own file/include layout) plus the root-level filelist.txt /
README.md / .child_reports.json, and (b) EVERY file the reaped-report ledger lists in
its `files` entries — children may author non-HDL support files (.mem/.h/…) that are
real promoted products; dropping one would make the next finalize's artifacts[] name a
missing path and crash promote. The tree walk prunes `runs/` (prior run workdirs, grows
monotonically) and promote internals instead of matching-then-filtering.

Adjudication artifacts are excluded by construction (room-birth hygiene, ARCHITECTURE
§7.2): result.json is never seeded (a carried-in stale envelope is reaped
blocked/stale_result). The judged review record (semantic-review.json) is copied ONLY
with --freeze — the freeze branch's byte-carry that keeps a `pin` on the record alive.
--freeze also materializes `fresh_reports.json` as `{}` when absent: a freeze round
dispatches zero children, and finalize's post exit gate hard-requires the file — an
empty map is that round's true reaped-report translation. First-run (no canonical dir)
is a no-op.

Canonical defaults to `{workdir}/../..`: the framework lays the workdir at
`<...>/Design/rtl-design/runs/<N>`, so the stage's canonical dir is the grandparent.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

PRODUCT_SUFFIXES = (".v", ".sv", ".vh", ".svh")
PRODUCT_FILES = ("filelist.txt", "README.md", ".child_reports.json")
FREEZE_EXTRAS = ("semantic-review.json",)
# pruned from the walk; these top-level dirs are never product homes.
_EXCLUDE_TOP = ("runs", ".promote-tmp", ".subagent_traces")


def _ledger_files(canonical: Path) -> list[Path]:
    """Containment-safe rel paths from the canonical ledger's `files` entries.
    Missing/corrupt ledger -> empty (the suffix walk still carries the HDL set)."""
    try:
        ledger = json.loads((canonical / ".child_reports.json").read_text())
        rels = []
        for rec in ledger.values():
            for f in rec.get("files", []):
                rel = Path(f)
                if rel.is_absolute() or ".." in rel.parts:
                    continue
                if (canonical / rel).is_file():
                    rels.append(rel)
        return rels
    except (OSError, ValueError, AttributeError):
        return []


def _product_rels(canonical: Path) -> list[Path]:
    rels = []
    for dirpath, dirnames, filenames in os.walk(canonical):
        if Path(dirpath) == canonical:
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_TOP]
        for fn in filenames:
            rel = Path(dirpath, fn).relative_to(canonical)
            if fn.endswith(PRODUCT_SUFFIXES) or (
                len(rel.parts) == 1 and fn in PRODUCT_FILES
            ):
                rels.append(rel)
    rels.extend(_ledger_files(canonical))
    return sorted(set(rels))


def seed(canonical: Path, workdir: Path, freeze: bool = False) -> list:
    copied: list = []
    if not canonical.is_dir():
        return copied
    rels = _product_rels(canonical)
    if freeze:
        rels += [Path(f) for f in FREEZE_EXTRAS if (canonical / f).is_file()]
    for rel in rels:
        dst = workdir / rel
        if dst.exists():  # no-clobber: keep freshly-authored work
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(canonical / rel, dst)
        copied.append(str(rel))
    if freeze:
        # Zero children are dispatched on a freeze round; materialize that round's true
        # reaped-report translation so finalize's post exit gate can close the run
        # (its absence fails finalize with artifacts=[] — a canonical-wiping promote).
        fresh = workdir / "fresh_reports.json"
        if not fresh.exists():
            fresh.write_text("{}\n")
            copied.append("fresh_reports.json")
    return copied


def run(workdir, canonical=None, freeze: bool = False) -> int:
    workdir = Path(workdir)
    canonical = (
        Path(canonical) if canonical is not None else workdir.resolve().parent.parent
    )
    copied = seed(canonical, workdir, freeze=freeze)
    print(json.dumps({"seeded": copied, "count": len(copied)}, ensure_ascii=False))
    return 0
