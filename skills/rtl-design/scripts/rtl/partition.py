#!/usr/bin/env python3
"""rtl exit gate — the ledger's roster against the manifest, and the artifacts enumeration.

Both of the checks here defend the same thing: `artifacts[]` IS the new canonical view, and
promote deletes what it omits and raises on what it cannot find. `artifacts` is the envelope
shape (array of {path} objects); a flat string list would break the framework's per-artifact
promote + envelope schema-validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from rtl._ledger import ANNOTATIONS_NAME, FILES_NAME, LedgerError, load_ledger


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _ledger_files(ledger: dict) -> list:
    return sorted({f for rec in ledger.values() for f in rec["files"]})


def _artifacts(ledger: dict, workdir: Path) -> list:
    """Every child's files plus the two sidecars, in the envelope shape. A file the sidecars
    name and no child wrote is dropped rather than listed: promote hardlinks every entry and
    raises on the first absent one, which happens BEFORE the outcome event is appended — so the
    round would hang with nothing in the log to schedule a repair from."""
    files = [f for f in _ledger_files(ledger) if (workdir / f).is_file()]
    return [{"path": p} for p in files + [FILES_NAME, ANNOTATIONS_NAME]]


def ledger_artifacts(workdir: Path) -> list:
    """The artifacts[] enumeration off disk. Raises LedgerError when a sidecar is unreadable."""
    return _artifacts(load_ledger(workdir), Path(workdir))


def exit_artifacts(manifest: Path, workdir: Path) -> list:
    """artifacts[] for a passing round: every child's files plus the two sidecars.

    Raises LedgerError when the workdir cannot yield one — a sidecar that is unreadable or
    schema-invalid, a manifest child with no ledger entry, or a file the sidecars name and no
    child wrote. Each would promote a canonical view short of the RTL it claims to hold.
    """
    roster = _read_json(manifest)
    ledger = load_ledger(workdir)

    missing = [c["name"] for c in roster["children"] if c["name"] not in ledger]
    if missing:
        raise LedgerError(
            f"{FILES_NAME} / {ANNOTATIONS_NAME} are missing "
            + ", ".join(missing)
            + " — every "
            "manifest child needs an entry, carried forward from the last round when this "
            "round did not re-author it"
        )

    absent = [f for f in _ledger_files(ledger) if not (workdir / f).is_file()]
    if absent:
        raise LedgerError(
            f"{FILES_NAME} names files that are not in the workdir: "
            + ", ".join(absent)
            + " — re-dispatch the child that owns them"
        )

    return _artifacts(ledger, workdir)
