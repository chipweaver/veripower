"""rtl._ledger — shared ledger helpers (load/validate/merge) for the rtl-design CLI.

The ledger (.child_reports.json) maps child-name -> {files, incdirs?, annotations}.
It is the single input the finalize scripts read, so they are pure functions of it.

- merge_filter(): overlay fresh subset reports onto the seeded prior ledger, then drop
  any child absent from the live manifest roster (manifest-shrink eviction).
- load_ledger(): read + shape-validate, raising LedgerError on a malformed/partial ledger
  (fail-loud — never let a finalize script emit degraded output from a bad ledger).
"""

from __future__ import annotations

import json
from pathlib import Path

_REQUIRED = ("files", "annotations")


class LedgerError(Exception):
    """Malformed ledger — finalize must fail loudly, never emit degraded output."""


def merge_filter(seeded: dict, fresh: dict, manifest_children: list) -> dict:
    """Overlay fresh onto seeded, then keep only keys in the live manifest roster."""
    roster = set(manifest_children)
    merged = {**seeded, **fresh}
    return {name: rec for name, rec in merged.items() if name in roster}


def _validate_record(name: str, rec) -> None:
    if not isinstance(rec, dict):
        raise LedgerError(f"child {name!r}: record must be an object")
    for k in _REQUIRED:
        if k not in rec:
            raise LedgerError(f"child {name!r}: missing required key {k!r}")
    if not isinstance(rec["files"], list):
        raise LedgerError(f"child {name!r}: 'files' must be a list")
    ann = rec["annotations"]
    if not isinstance(ann, dict) or "sgdc" not in ann or "sdc" not in ann:
        raise LedgerError(
            f"child {name!r}: 'annotations' needs 'sgdc' and 'sdc' blocks"
        )
    for block in ("sgdc", "sdc"):
        if not isinstance(ann[block], dict):
            raise LedgerError(
                f"child {name!r}: 'annotations.{block}' must be an object"
            )


def load_ledger(path) -> dict:
    """Read + shape-validate the ledger. Raise LedgerError on any defect."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise LedgerError(f"cannot read ledger {path}: {e}") from e
    if not isinstance(data, dict):
        raise LedgerError(f"ledger {path}: top level must be an object")
    for name, rec in data.items():
        _validate_record(name, rec)
    return data
