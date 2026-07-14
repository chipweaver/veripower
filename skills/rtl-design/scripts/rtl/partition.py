#!/usr/bin/env python3
"""rtl exit gate — top-module coverage + purity (pre) and blocked-child precedence +
artifacts enumeration (post).

Two verdicts, one cohesive module (they were adjacent and coupled in the source):
  coverage_verdict(manifest, top)        -> (status, reason)   # pre: manifest+top only
  post_verdict(manifest, top, fresh, ledger) -> (verdict, rc)  # post: + blocked-child + artifacts

`run()` is the `check-partition` verb (the pre gate) — a one-line verdict JSON on stdout,
status truth = exit code (0 pass / 1 fail). `assemble` and `result` import `post_verdict`.
`artifacts` is the envelope shape (array of {path} objects); a flat string list would break
the framework's per-artifact promote + envelope schema-validation.
"""

from __future__ import annotations

import json
from pathlib import Path

from rtl._ledger import load_ledger


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


def post_verdict(manifest: Path, top: str, fresh: Path, ledger: Path):
    """The post exit verdict: coverage+purity + blocked-child precedence + the artifacts[]
    enumeration from the ledger. Returns (verdict_dict, rc). The single copy assemble's run()
    and result's build_result both reuse — no behavior change, only factored out."""
    status, reason = coverage_verdict(manifest, top)
    if status == "fail" and not ledger.exists():
        # Pre-dispatch coverage fail (no fan-out yet, so no ledger): surface the real coverage
        # reason (never None on a fail) so `finalize` can write it, instead of the generic
        # "requires fresh + ledger" message below. In assemble.run the ledger is always written
        # before this call, so this branch is reached only from the pre-dispatch finalize path.
        return {"status": "fail", "artifacts": [], "fail_reason": reason}, 1
    if not (fresh.exists() and ledger.exists()):
        return (
            {
                "status": "fail",
                "artifacts": [],
                "fail_reason": "post exit gate requires fresh_reports.json and the ledger",
            },
            1,
        )
    fresh_data = _read_json(fresh)
    ledger_data = load_ledger(ledger)
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

    files = sorted({f for rec in ledger_data.values() for f in rec["files"]})
    paths = files + ["filelist.txt", "README.md", ".child_reports.json"]
    artifacts = [{"path": p} for p in paths]
    verdict = {"status": status, "artifacts": artifacts}
    if reason:
        verdict["fail_reason"] = reason
    return verdict, (0 if status == "pass" else 1)


def run(manifest, top) -> int:
    """check-partition verb: the pre-dispatch coverage+purity gate (manifest+top only)."""
    status, reason = coverage_verdict(Path(manifest), top)
    verdict = {"status": status, "artifacts": []}
    if reason:
        verdict["fail_reason"] = reason
    print(json.dumps(verdict, ensure_ascii=False))
    return 0 if status == "pass" else 1
