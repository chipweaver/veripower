#!/usr/bin/env python3
"""rtl finalize — assemble the lean rtl-design result.json (exit gate + folded semantic gate).

Re-derives the exit verdict in-process over the converged ledger (status / fail_reason /
artifacts, verbatim via partition.post_verdict), then on a passing exit folds in the
semantic gate via the pure review.compute_gate (no subprocess, no schema-gate re-hit). A
semantic gate=trip flips a passing exit to fail with a locus-tagged fail_reason (spec-rooted
named first, else rtl-local). result.json is fully script-derived (run narration lives in
events.jsonl). Exit 0 = result.json written (pass or fail); exit 2 = BLOCKED (internal raise).
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

from rtl.partition import post_verdict
from rtl.review import compute_gate

STAGE = "rtl-design"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _envelope(module, *, status, stage_specific, artifacts) -> dict:
    return {
        "schema_version": 1,
        "stage": STAGE,
        "module": module,
        "produced_at": _now_iso(),
        "status": status,
        "artifacts": artifacts,
        "stage_specific": stage_specific,
    }


def _write_result(workdir: Path, env: dict) -> None:
    tmp = workdir / "result.json.tmp"
    tmp.write_text(json.dumps(env, indent=2) + "\n")
    tmp.replace(workdir / "result.json")  # atomic: never observed half-written
    sys.stdout.write(
        f"[rtl finalize] Written: {workdir / 'result.json'} (status={env['status']})\n"
    )


def _exit_verdict(workdir: Path, top: str, manifest: Path) -> dict:
    """Re-derive the **post exit-gate** verdict IN-PROCESS over the converged on-disk state:
    {status, fail_reason?, artifacts[]}. Calls the same post_verdict() the legacy CLI uses,
    so the topology/blocked-child gate + artifact enumeration are not duplicated."""
    return post_verdict(manifest, top, workdir / "reaped-children.json", workdir)[0]


def _locus_fail_reason(gate: dict) -> str:
    """Mechanize the semantic-trip fail narrative: a spec-locus trip is named first, else rtl-local."""
    flagged = gate.get("flagged", [])
    loci = gate.get("loci", {})
    first = flagged[0]
    extra = f" (+{len(flagged) - 1} more)" if len(flagged) > 1 else ""
    if loci.get("spec"):
        return f"semantic gate: spec-rooted intent defect — {first['child']}{extra}"
    return f"semantic gate: rtl-local intent defect — {first['child']}{extra}"


def build_result(workdir, module, top, manifest) -> int:
    """Assemble the lean rtl-design result.json from the converged on-disk workdir.
    Re-derives the exit verdict in-process (status/fail_reason/artifacts, verbatim), then on a
    passing exit folds in the semantic gate via the pure compute_gate() (in-process, no subprocess,
    no schema-gate re-hit). A semantic gate=trip flips a passing exit to fail with a locus-tagged
    fail_reason. Adds top_module, drops the free-text note. result.json is fully script-derived —
    no agent input (run narration lives in events.jsonl). Returns 0 (result.json written, pass or
    fail). A raise → main() exit 2 (BLOCKED). Field set per the field-necessity verdict (Task 0)."""
    workdir, manifest = Path(workdir), Path(manifest)
    exit_v = _exit_verdict(workdir, top, manifest)
    artifacts = list(exit_v.get("artifacts", []))

    if exit_v.get("status") != "pass":
        # topology / blocked-child fail — verbatim verdict; the semantic gate was never reached.
        ss = {
            "top_module": top,
            "fail_reason": exit_v.get("fail_reason", "rtl exit gate failed"),
        }
        _write_result(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0

    # exit verdict passed -> fold in the semantic gate via the pure fn (already-validated doc).
    # Read as-is: review-vs-content freshness is a process invariant — the skill re-runs its
    # gate on the current RTL before finalize (SKILL.md "Re-entry and completion"), not enforced here.
    review = json.loads((workdir / "semantic-review.json").read_text(encoding="utf-8"))
    gate = compute_gate(review)
    artifacts.append({"path": "semantic-review.json"})
    if gate.get("gate") == "trip":
        ss = {
            "top_module": top,
            "semantic_gate": gate,
            "fail_reason": _locus_fail_reason(gate),
        }
        _write_result(
            workdir,
            _envelope(module, status="fail", stage_specific=ss, artifacts=artifacts),
        )
        return 0
    ss = {"top_module": top, "semantic_gate": gate}
    _write_result(
        workdir,
        _envelope(module, status="pass", stage_specific=ss, artifacts=artifacts),
    )
    return 0


def finalize(workdir, module, top, manifest) -> int:
    """Assemble the lean rtl-design result.json from the converged workdir.
    exit 0 = result.json written (status pass or fail); exit 2 = BLOCKED (any internal
    raise) — never conflated with status=fail. (Owns the policy the deleted main() had.)"""
    try:
        return build_result(workdir, module, top, manifest)
    except Exception as exc:  # noqa: BLE001 — any failure to operate is BLOCKED
        print(f"[rtl finalize] FAIL=internal {exc}", file=sys.stderr)
        return 2
