#!/usr/bin/env python3
"""Produce the canonical .child_reports.json ledger for an rtl-design run.

Merge freshly-reaped child reports (fresh_reports.json) onto the seeded prior ledger
(present only on incremental/rework runs), keep only children in the live manifest
roster, shape-validate, and write the ledger. Done children only — a blocked
child has no ledger entry.

Usage:
  build_ledger.py --fresh <fresh_reports.json> --manifest <manifest.json>
                  --out <workdir/.child_reports.json> [--seeded <prior .child_reports.json>]
Exit: non-zero + stderr on any defect (fail-loud).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
from ledger_io import LedgerError, load_ledger, merge_filter  # noqa: E402


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fresh", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--seeded", type=Path, default=None)
    a = ap.parse_args()

    fresh_raw = _read_json(a.fresh)
    fresh = {}
    for name, rec in fresh_raw.items():
        if rec.get("status") != "done":
            continue
        # A done child MUST carry its required contract fields; a missing 'files'
        # would otherwise be silently defaulted, dropping that child's RTL from the
        # filelist (Iron Rule #1). Fail loud on the contract violation instead.
        for req in ("files", "annotations"):
            if req not in rec:
                print(
                    f"build_ledger: done child {name!r} missing required {req!r}",
                    file=sys.stderr,
                )
                return 1
        entry = {"files": rec["files"], "annotations": rec["annotations"]}
        if "incdirs" in rec:
            entry["incdirs"] = rec["incdirs"]
        fresh[name] = entry

    seeded = load_ledger(a.seeded) if (a.seeded and a.seeded.is_file()) else {}
    roster = [c["name"] for c in _read_json(a.manifest).get("children", [])]

    ledger = merge_filter(seeded, fresh, roster)
    a.out.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    try:  # fail-loud: never leave a malformed ledger on disk silently
        load_ledger(a.out)
    except LedgerError as e:
        print(f"build_ledger: produced malformed ledger: {e}", file=sys.stderr)
        return 1
    print(
        json.dumps({"children": list(ledger), "count": len(ledger)}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
