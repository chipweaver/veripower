#!/usr/bin/env python3
"""rtl-design exit gate: R-1 top-module coverage + child-status precedence.

Emits a one-line JSON verdict on stdout that the main thread copies verbatim into result.json:
  {"status": "pass|fail", "fail_reason"?: str, "artifacts": [{"path": str}, ...]}
`artifacts` is the envelope shape (array of {path} objects) — the framework promotes each
artifact by its path and schema-validates the envelope at stage completion; a flat string
list would break both.

Status truth = exit code (0 pass / 1 fail), NOT narration. On a gate-fail this script exits 1 with
the fail_reason inside the stdout verdict and EMPTY stderr by design — the verdict JSON is the single
source (the main thread reads status/fail_reason/artifacts from stdout, never stderr, for this script).
Does NOT schema-validate result.json — the framework does that at stage completion.

Usage:
  validate_rtl_exit.py --manifest <manifest.json> --top <top_module>
                       [--phase {pre,post}]
                       [--fresh <fresh_reports.json>] [--ledger <.child_reports.json>]
  --phase pre  : manifest+top only (no reports); for pre-dispatch fail-fast.
  --phase post : (default) also folds in blocked-child check + emits artifacts from ledger;
                 requires --fresh and --ledger.
Exit: 0 if status==pass, 1 if status==fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
from ledger_io import load_ledger  # noqa: E402


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--top", required=True)
    ap.add_argument("--phase", choices=["pre", "post"], default="post")
    ap.add_argument("--fresh", type=Path)
    ap.add_argument("--ledger", type=Path)
    a = ap.parse_args()

    children = _read_json(a.manifest).get("children", [])
    covering = [c for c in children if a.top in c.get("rtl_modules", [])]

    status, reason = "pass", None
    if len(covering) != 1:
        status = "fail"
        reason = (
            f"exit-check: top_module '{a.top}' covered by {len(covering)} children "
            f"(expected 1) — specification must emit exactly one top-integration child"
        )
    elif covering[0].get("rtl_modules") != [a.top]:
        status = "fail"
        reason = (
            f"exit-check: top-integration child '{covering[0]['name']}' is not pure: "
            f"rtl_modules={covering[0].get('rtl_modules')} (expected ['{a.top}'] only) — "
            f"specification must not bundle logic modules with the top module"
        )

    # --phase pre: coverage + purity only, from manifest+top (no reaped reports, nothing authored yet).
    if a.phase == "pre":
        verdict = {"status": status, "artifacts": []}
        if reason:
            verdict["fail_reason"] = reason
        print(json.dumps(verdict, ensure_ascii=False))
        return 0 if status == "pass" else 1

    # --phase post: also fold in the blocked-child precedence + emit artifacts from the ledger.
    if not (a.fresh and a.ledger):
        print(
            json.dumps(
                {
                    "status": "fail",
                    "artifacts": [],
                    "fail_reason": "validate_rtl_exit --phase post requires --fresh and --ledger",
                },
                ensure_ascii=False,
            )
        )
        return 1
    fresh = _read_json(a.fresh)
    ledger = load_ledger(a.ledger)
    if status == "pass":
        blocked = {
            n: r.get("reason", "")
            for n, r in fresh.items()
            if r.get("status") == "blocked"
        }
        if blocked:
            status = "fail"
            reason = "child blocked: " + "; ".join(
                f"{n}: {m}" for n, m in blocked.items()
            )

    files = sorted({f for rec in ledger.values() for f in rec["files"]})
    paths = files + ["filelist.txt", "README.md", ".child_reports.json"]
    # Envelope shape: artifacts MUST be an array of {"path": ...} objects (the framework promotes each
    # artifact by path + schema-validates the envelope); a flat string list would break both.
    artifacts = [{"path": p} for p in paths]
    verdict = {"status": status, "artifacts": artifacts}
    if reason:
        verdict["fail_reason"] = reason
    print(json.dumps(verdict, ensure_ascii=False))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
