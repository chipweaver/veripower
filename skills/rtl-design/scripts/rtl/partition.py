#!/usr/bin/env python3
"""rtl exit gate — top-module coverage + purity (pre) and blocked-child precedence +
artifacts enumeration (post).

Two verdicts over one shared coverage rule:
  coverage_verdict(manifest, top)              -> (status, reason)  # pre: manifest+top only
  post_verdict(manifest, top, fresh, workdir)  -> (verdict, rc)     # post: + blocked-child
  ledger_artifacts(workdir)                    -> artifacts[]       # the enumeration both use

`result` imports `post_verdict`; `coverage_verdict` is also run by specification's own
check-coverage gate, and tests/contracts/test_partition_purity_agreement.py locks the two
implementations together. `artifacts` is the envelope shape (array of {path} objects); a flat string list would break
the framework's per-artifact promote + envelope schema-validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from rtl._ledger import ANNOTATIONS_NAME, FILES_NAME, ledger_exists, load_ledger


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


def ledger_artifacts(workdir: Path) -> list:
    """The artifacts[] enumeration: every child's files plus the two sidecars, in the envelope
    shape. Raises LedgerError when the sidecars are unreadable."""
    files = sorted({f for rec in load_ledger(workdir).values() for f in rec["files"]})
    return [{"path": p} for p in files + [FILES_NAME, ANNOTATIONS_NAME]]


def post_verdict(manifest: Path, top: str, fresh: Path, workdir: Path):
    """The post exit verdict: coverage+purity + blocked-child precedence + the artifacts[]
    enumeration from the ledger. Returns (verdict_dict, rc). The single copy assemble's run()
    and result's build_result both reuse."""
    status, reason = coverage_verdict(manifest, top)
    if status == "fail" and not ledger_exists(workdir):
        # Pre-dispatch coverage fail (no fan-out yet, so no ledger): surface the real coverage
        # reason (never None on a fail) so `finalize` can write it, instead of the generic
        # "requires fresh + ledger" message below. In assemble.run the ledger is always written
        # before this call, so this branch is reached only from the pre-dispatch finalize path.
        return {"status": "fail", "artifacts": [], "fail_reason": reason}, 1
    if not (fresh.exists() and ledger_exists(workdir)):
        # Reachable with the sidecars present but reaped-children.json gone. A fail envelope
        # promotes like a passing one and promote deletes every canonical entry artifacts[] omits,
        # so still enumerate a readable ledger: never under-report a live baseline into a wipe.
        return (
            {
                "status": "fail",
                "artifacts": ledger_artifacts(workdir)
                if ledger_exists(workdir)
                else [],
                "fail_reason": (
                    f"post exit gate requires reaped-children.json, {FILES_NAME} "
                    f"and {ANNOTATIONS_NAME}"
                ),
            },
            1,
        )
    fresh_data = _read_json(fresh)
    if status == "pass":
        blocked = {
            n: r.get("reason", "")
            for n, r in fresh_data.items()
            if r.get("status") == "blocked"
        }
        if blocked:
            status = "fail"
            reason = "child blocked: " + "; ".join(
                f"{n}: {m}" for n, m in blocked.items()
            )

    verdict = {"status": status, "artifacts": ledger_artifacts(workdir)}
    if reason:
        verdict["fail_reason"] = reason
    return verdict, (0 if status == "pass" else 1)
