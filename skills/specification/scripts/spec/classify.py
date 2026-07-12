#!/usr/bin/env python3
"""spec classify-delta — select the freeze branch: first-run | freeze | proceed.

Pure read + hash. Directive-agnostic: the SKILL consults it only on the
directive-less path (a directive means a scoped fix, never a freeze). freeze iff
brainstorm.md is byte-unchanged from the run that produced the canonical design.md
AND that run passed — then the producer copies its prior outputs + spec-review.json
forward (via `spec seed`) and skips the Step-7 semantic gate, keeping any pin alive.

input_digest() is the single home for the digest algorithm; spec.result imports it
so finalize records the same value the classifier later compares against.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def input_digest(brainstorm: str | Path) -> str:
    return hashlib.sha256(Path(brainstorm).read_bytes()).hexdigest()


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
    return {"verdict": "freeze", "reason": "brainstorm frozen, baseline pass"}


def run(canonical_result, brainstorm) -> int:
    """Verb entry: print the verdict JSON on stdout, exit 0 (missing input -> exit 1)."""
    if not Path(brainstorm).is_file():
        print(f"[spec classify-delta] missing input: {brainstorm}", file=sys.stderr)
        return 1
    print(json.dumps(classify_delta(canonical_result, brainstorm), ensure_ascii=False))
    return 0
