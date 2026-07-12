#!/usr/bin/env python3
"""simplan classify-delta — select the freeze branch: first-run | freeze | proceed.

Pure read + hash over the specification input set (design.md + manifest.json + each
<child>.md). Directive-agnostic: the SKILL consults it only on the directive-less path.
freeze iff the spec inputs are byte-unchanged from the run that produced the canonical
simulation-plan result AND that run passed — then `simplan seed` copies the prior
verification-plan.md / scaffold-specification.json AND plan-review.json forward, and the
Step-4 adequacy gate is skipped.

input_digest() is the single home for the digest algorithm; simplan.result imports it so
finalize records the same value the classifier later compares against.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def input_digest(spec_dir: str | Path) -> str:
    spec_dir = Path(spec_dir)
    files = sorted(set(spec_dir.glob("*.md")) | {spec_dir / "manifest.json"})
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def classify_delta(canonical_result, spec_dir) -> dict:
    current = input_digest(spec_dir)
    cr = Path(canonical_result) if canonical_result is not None else None
    if cr is None or not cr.is_file():
        return {"verdict": "first-run", "reason": "no canonical simulation-plan result"}
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
        return {"verdict": "proceed", "reason": "specification changed since baseline"}
    if status != "pass":
        return {"verdict": "proceed", "reason": f"baseline not pass (status={status})"}
    return {"verdict": "freeze", "reason": "specification frozen, baseline pass"}


def run(canonical_result, spec_dir) -> int:
    if not Path(spec_dir).is_dir():
        print(f"[simplan classify-delta] missing spec dir: {spec_dir}", file=sys.stderr)
        return 1
    print(json.dumps(classify_delta(canonical_result, spec_dir), ensure_ascii=False))
    return 0
