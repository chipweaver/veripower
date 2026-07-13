#!/usr/bin/env python3
"""sim classify-delta — select the Wave-1 branch: first-run | freeze | patch.

Pure read + hash. Trigger-agnostic: the verdict depends ONLY on the plan inputs
(verification-plan.md + scaffold-specification.json) and the baseline TB-validity, never on
{failing_result} -- the TB's sole upstream truth is the sim-plan exit docs. A baseline that failed
in {regress, coverage} still carries a complete, conformance-passed TB (the failure was
RTL/stimulus), so it is freeze-eligible. All other non-freeze cases yield patch: the prior TB is
copied into the run workdir and edited in-place (delta-only), rather than rebuilt from blank.
No canonical result / unreadable result / no materialized TB (e.g. prerequisite-fail baseline)
yields first-run instead -- there is nothing to copy. P1-A: a baseline whose conformance review
never really ran (an 'unavailable' stub) is also patch, not freeze -- freeze must not lock in
an unjudged TB. Correctness is backstopped by the round's full conformance re-judge; freeze is
the plan-bytes-unchanged + fully-judged zero-LLM fast path.

plan_digest() is the single home for the digest algorithm; sim.result imports it so finalize writes
the same value the classifier later compares against.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TB_VALID_FAIL_PHASES = {"regress", "coverage"}


def plan_digest(scaffold: str | Path, plan: str | Path) -> str:
    h = hashlib.sha256()
    h.update(Path(scaffold).read_bytes())
    h.update(b"\0")  # separator: close the two-file byte-split boundary ambiguity
    h.update(Path(plan).read_bytes())
    return h.hexdigest()


def _conformance_real(canonical_result: Path) -> bool:
    """True iff the baseline ran a REAL conformance review (P1-A): a sibling
    conformance-review.json that exists, parses, and carries no 'unavailable' finding."""
    cr = canonical_result.parent / "conformance-review.json"
    if not cr.is_file():
        return False
    try:
        data = json.loads(cr.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return not any(f.get("category") == "unavailable" for f in data.get("findings", []))


def classify_delta(canonical_result, scaffold, plan) -> dict:
    current = plan_digest(scaffold, plan)
    cr = Path(canonical_result)
    if not cr.is_file():
        return {"verdict": "first-run", "reason": "no canonical simulation result"}
    try:
        rj = json.loads(cr.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"verdict": "first-run", "reason": "canonical result unreadable"}
    if not (cr.parent / "tb" / "uvm").is_dir():
        # no TB to copy (e.g. prerequisite-fail baseline never built one) -> scaffold fresh
        return {"verdict": "first-run", "reason": "no canonical TB to copy"}
    ss = rj.get("stage_specific", {})
    status, recorded = rj.get("status"), ss.get("plan_digest")
    if recorded is None:
        return {
            "verdict": "patch",
            "reason": "baseline has no plan_digest (unjudged/legacy TB)",
        }
    if recorded != current:
        return {"verdict": "patch", "reason": "plan changed since baseline"}
    tb_valid = status == "pass" or (
        status == "fail" and ss.get("failure_phase") in TB_VALID_FAIL_PHASES
    )
    if not tb_valid:
        return {
            "verdict": "patch",
            "reason": f"baseline TB not fully judged (status={status}, failure_phase={ss.get('failure_phase')})",
        }
    if not _conformance_real(cr):
        return {
            "verdict": "patch",
            "reason": "baseline conformance unavailable/absent (P1-A)",
        }
    return {
        "verdict": "freeze",
        "reason": "plan frozen, baseline TB valid, conformance real",
    }


def run(canonical_result, scaffold, plan) -> int:
    """Verb entry: print the verdict JSON on stdout, exit 0. canonical_result None => first-run."""
    if canonical_result is None:
        print(
            json.dumps(
                {"verdict": "first-run", "reason": "no canonical result"},
                ensure_ascii=False,
            )
        )
        return 0
    for pth in (scaffold, plan):
        if not Path(pth).is_file():
            print(f"[sim classify-delta] missing plan input: {pth}", file=sys.stderr)
            return 1
    print(
        json.dumps(classify_delta(canonical_result, scaffold, plan), ensure_ascii=False)
    )
    return 0
