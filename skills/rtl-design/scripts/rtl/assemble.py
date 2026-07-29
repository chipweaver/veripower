#!/usr/bin/env python3
"""rtl assemble — write the two sidecars, then run the post exit-gate.

The reaped child reports become rtl-files.json + constraint-annotations.json; every
downstream filelist is generated from the former and the constraint annotations are read
from the latter, so this verb renders no text projection of either. The 4.3 conformance
loop re-runs `assemble --seeded` every round, so this is safe to re-call.

stdout/exit contract:
  * BUILD ERROR (malformed/contract-violating reports or state): exit 1, message on
    STDERR, and NO stdout verdict — the main thread reads stderr as the fail_reason.
  * otherwise: write the sidecars, then print the post-gate verdict JSON on STDOUT;
    exit code = truth (0 pass / 1 fail). The presence of a stdout verdict is how the
    main thread tells a gate fail apart from a build error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rtl._ledger import (
    LedgerError,
    ledger_exists,
    load_ledger,
    merge_filter,
    write_ledger,
)
from rtl.partition import post_verdict


class _BuildError(Exception):
    """A reports/ledger contract violation — fail loud, never emit degraded output."""


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def merge_ledger(fresh: Path, manifest: Path, workdir: Path, seeded: bool) -> dict:
    """Merge fresh done-child reports onto any seeded prior state, keep only the manifest
    roster, write both sidecars, and return the merged dict. Raises _BuildError /
    LedgerError on any contract violation (fail-loud)."""
    fresh_raw = _read_json(fresh)
    merged_fresh = {}
    for name, rec in fresh_raw.items():
        if rec.get("status") != "done":
            continue
        # A done child MUST carry its required contract fields; a missing 'files' would
        # otherwise be silently defaulted, dropping that child's RTL from the filelist
        # (Iron Rule #1). Fail loud on the contract violation instead.
        for req in ("files", "annotations"):
            if req not in rec:
                raise _BuildError(f"done child {name!r} missing required {req!r}")
        entry = {"files": rec["files"], "annotations": rec["annotations"]}
        if "incdirs" in rec:
            entry["incdirs"] = rec["incdirs"]
        merged_fresh[name] = entry

    seeded_ledger = load_ledger(workdir) if (seeded and ledger_exists(workdir)) else {}
    roster = [c["name"] for c in _read_json(manifest).get("children", [])]
    ledger = merge_filter(seeded_ledger, merged_fresh, roster)

    write_ledger(workdir, ledger)  # validates first: no degraded state on disk
    return ledger


def run(workdir, manifest, top, *, seeded=False) -> int:
    workdir, manifest = Path(workdir), Path(manifest)
    fresh = workdir / "reaped-children.json"
    try:
        merge_ledger(fresh, manifest, workdir, seeded)
    except (_BuildError, LedgerError, json.JSONDecodeError, OSError, KeyError) as e:
        print(f"[rtl assemble] {e}", file=sys.stderr)
        return 1
    verdict, rc = post_verdict(manifest, top, fresh, workdir)
    print(json.dumps(verdict, ensure_ascii=False))
    return rc
