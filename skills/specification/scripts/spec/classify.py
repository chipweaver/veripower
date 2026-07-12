#!/usr/bin/env python3
"""spec classify-delta — select the freeze branch: first-run | freeze | proceed.

Pure read + hash. Directive-agnostic: the SKILL consults it only on the
directive-less path (a directive means a scoped fix, never a freeze). freeze iff
BOTH halves hold: (1) brainstorm.md is byte-unchanged from the run that produced
the canonical result AND that run passed; (2) the canonical products still match
the products_digest that pass recorded — brainstorm-unchanged alone is not enough,
because a hand-edited canonical product would otherwise be re-blessed by the freeze
branch without any reviewer wave or human gate seeing it. Either digest absent
(legacy baseline) → proceed, never freeze (safe fallback).

input_digest() / products_digest() are the single home for both digest algorithms;
spec.result imports them so finalize records the same values the classifier later
compares against.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def input_digest(brainstorm: str | Path) -> str:
    return hashlib.sha256(Path(brainstorm).read_bytes()).hexdigest()


def products_digest(root: str | Path, artifact_paths: list[str]) -> str:
    """Digest over an artifact set (sorted relative paths + per-file content hash) —
    the freeze check's second half. Raises OSError when any listed file is missing
    or unreadable (the caller treats that as no-freeze)."""
    h = hashlib.sha256()
    for rel in sorted(artifact_paths):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256((Path(root) / rel).read_bytes()).digest())
    return h.hexdigest()


def classify_delta(canonical_result, brainstorm) -> dict:
    current = input_digest(brainstorm)
    cr = Path(canonical_result) if canonical_result is not None else None
    if cr is None or not cr.is_file():
        return {"verdict": "first-run", "reason": "no canonical specification result"}
    try:
        rj = json.loads(cr.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"verdict": "first-run", "reason": "canonical result unreadable"}
    if not isinstance(rj, dict):
        return {"verdict": "first-run", "reason": "canonical result unreadable"}
    ss = rj.get("stage_specific", {})
    if not isinstance(ss, dict):
        ss = {}
    status, recorded = rj.get("status"), ss.get("input_digest")
    if recorded is None:
        return {"verdict": "proceed", "reason": "baseline has no recorded input_digest"}
    if recorded != current:
        return {"verdict": "proceed", "reason": "brainstorm changed since baseline"}
    if status != "pass":
        return {"verdict": "proceed", "reason": f"baseline not pass (status={status})"}
    recorded_products = ss.get("products_digest")
    if recorded_products is None:
        return {"verdict": "proceed", "reason": "baseline has no products_digest"}
    paths = [
        a.get("path")
        for a in rj.get("artifacts", [])
        if isinstance(a, dict) and a.get("path")
    ]
    try:
        current_products = products_digest(cr.parent, paths)
    except OSError:
        return {"verdict": "proceed", "reason": "canonical products missing/unreadable"}
    if current_products != recorded_products:
        return {
            "verdict": "proceed",
            "reason": "canonical products drifted since baseline",
        }
    return {
        "verdict": "freeze",
        "reason": "brainstorm + products unchanged, baseline pass",
    }


def run(canonical_result, brainstorm) -> int:
    """Verb entry: print the verdict JSON on stdout, exit 0 (missing input -> exit 1)."""
    if not Path(brainstorm).is_file():
        print(f"[spec classify-delta] missing input: {brainstorm}", file=sys.stderr)
        return 1
    print(json.dumps(classify_delta(canonical_result, brainstorm), ensure_ascii=False))
    return 0
