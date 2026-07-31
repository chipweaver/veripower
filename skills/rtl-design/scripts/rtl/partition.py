#!/usr/bin/env python3
"""rtl exit gate — top-module coverage + purity, the ledger's roster, and artifacts enumeration.

`coverage_verdict` is the same rule specification decides at `derive-ports`, and
tests/contracts/test_partition_purity_agreement.py locks the two implementations together.
`artifacts` is the envelope shape (array of {path} objects); a flat string list would break the
framework's per-artifact promote + envelope schema-validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from rtl._ledger import ANNOTATIONS_NAME, FILES_NAME, LedgerError, load_ledger


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def coverage_verdict(manifest: Path, top: str):
    """Coverage + purity over manifest+top (no reports). Returns (status, reason)."""
    children = _read_json(manifest).get("children", [])
    covering = [c for c in children if top in c.get("rtl_modules", [])]
    if len(covering) != 1:
        return "fail", (
            f"exit-check: top_module '{top}' covered by {len(covering)} children "
            f"(expected 1) — specification must emit exactly one top-integration child"
        )
    if covering[0].get("rtl_modules") != [top]:
        return "fail", (
            f"exit-check: top-integration child '{covering[0]['name']}' is not pure: "
            f"rtl_modules={covering[0].get('rtl_modules')} (expected ['{top}'] only) — "
            f"specification must not bundle logic modules with the top module"
        )
    return "pass", None


def _artifacts(ledger: dict) -> list:
    """Every child's files plus the two sidecars, in the envelope shape."""
    files = sorted({f for rec in ledger.values() for f in rec["files"]})
    return [{"path": p} for p in files + [FILES_NAME, ANNOTATIONS_NAME]]


def ledger_artifacts(workdir: Path) -> list:
    """The artifacts[] enumeration off disk. Raises LedgerError when a sidecar is unreadable."""
    return _artifacts(load_ledger(workdir))


def post_verdict(manifest: Path, top: str, workdir: Path):
    """The exit verdict: coverage+purity, the ledger's roster against the manifest, and the
    artifacts[] enumeration. Returns (verdict_dict, rc)."""
    status, reason = coverage_verdict(manifest, top)
    ledger = load_ledger(workdir)
    if status == "fail":
        return {
            "status": status,
            "artifacts": _artifacts(ledger),
            "fail_reason": reason,
        }, 1

    missing = [
        c["name"] for c in _read_json(manifest)["children"] if c["name"] not in ledger
    ]
    if missing:
        # artifacts[] is the new canonical view and promote deletes what it omits, so a ledger
        # short of the roster would silently drop those children's RTL out of canonical while
        # reporting a pass. Nothing here can name the files it does not have: refuse instead.
        raise LedgerError(
            f"{FILES_NAME} / {ANNOTATIONS_NAME} are missing "
            + ", ".join(missing)
            + " — every "
            "manifest child needs an entry, carried forward from the last round when this "
            "round did not re-author it"
        )
    return {"status": "pass", "artifacts": _artifacts(ledger)}, 0
